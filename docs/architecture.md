# 架构

> 一句话：**采集端是无状态哑管道，云端是唯一有状态的提炼者。** 任何记忆能力都不在请求路径上。
>
> 适用范围：系统拓扑、组件职责、故障隔离约束与部署形态。
> 不负责：环境变量键值（见 [tech/ENVIRONMENT.md](tech/ENVIRONMENT.md)）、跨端字段契约（见 [contracts/](contracts/README.md)）、实施历史（见 [CHANGELOG.md](CHANGELOG.md)）。

## 1. 拓扑

```
 ┌─ 设备 A ─────────────┐         ┌─ 设备 B ─────────────┐
 │ agent-console        │         │ agent-console        │
 │  └─ collector        │         │  └─ collector        │
 │     读 sources.json  │         │     读 sources.json  │
 └─────────┬────────────┘         └─────────┬────────────┘
           │  HTTPS 推送增量（只出不进）      │
           ▼                                ▼
 ┌─────────────────────── memhub.work (43.142.18.23) ──────────────────────┐
 │  nginx                                                                  │
 │   /api/v1/ingest/*  → ingest-api (FastAPI)                              │
 │   /api/v1/kb/*      → kb-api                                            │
 │   /mcp              → mcp-server (streamable HTTP)                      │
 │   /                → explorer (只读可视化)                               │
 ├─────────────────────────────────────────────────────────────────────────┤
 │  ingest-api / kb-api(上传) → queue.rawstore (原始增量, 按 device/source)  │
 │           → runtime state (PostgreSQL: 设备/游标/批次幂等, memhub_prod)   │
 │  worker:  value_filter(cheap) → extract(expensive) → merge              │
 │  merge → knowledge/ (markdown 真源, git) → rebuild projections          │
 │  projections: kg.json | vector/ | fts.db                                │
 └─────────────────────────────────────────────────────────────────────────┘
           ▲
           │ 只读
 ┌─────────┴──────────────┐
 │ 多台机器上的 agent      │  ← MCP / CLI，走 memhub.work，不经任何本地代理
 └────────────────────────┘
```

## 2. 与旧 memhub 的关键差异

| 旧 | 新 |
|---|---|
| Memory Proxy 在模型请求路径上 | 请求路径上没有 memhub；模型直连 Magpie |
| 记忆失败 = 模型不可用 | 采集/提炼失败只影响记忆新鲜度，用户正常工作 |
| Team Brain MCP 本地进程 + 共享 key | 远端 `/mcp`，per-device token，可吊销 |
| 会话靠 Proxy 旁路抓取 | collector 直接读本地 session 文件，游标增量 |
| 状态散在 Proxy/本地 relay | 状态只在云端（raw_store + 游标 + 知识库） |
| 数据格式即实现 | markdown 真源 + 可重建投影 |

## 3. 组件职责

### collector（客户端，e4 负责）
- 读 `sources.json`；按 interval 扫描；按 `GET /ingest/cursor` 对齐。
- 只做字节搬运：切增量、算 sha256、打包、压缩、推送、落本地 state。
- **不做**任何解析、抽取、判断。无 UI（配置由桌面端写入），systemd/launchd/计划任务托管。
- 崩溃恢复：state 文件原子写；未确认批次重推（服务端按 batch_id 幂等）。

### ingest-api（服务端）
- 鉴权、游标、幂等、限流、落 raw_store、入队。
- 只做校验，不做 LLM 调用，响应 <200ms。

### queue（跨模块落盘与配额，非独立进程）
- `memhub.queue.rawstore`：raw_store 的内容寻址布局、原子写、用量估算与配额（`MEMHUB_QUEUE_MAX_BYTES`）。
- 写入方：ingest-api 的 `/ingest/raw`、kb-api 的知识库上传；读取方只有 worker。
- 放在 `queue/` 而不是 `ingest/`：上传入口不该依赖采集协议层（鉴权、游标、<200ms 约束）；鉴权、游标校验与错误码映射留在各自路由层，这里只做与协议无关的落盘与计量。

### worker（服务端，单机串行 + 少量并发）
```
raw 片段 ──► value_filter ──► extract ──► merge ──► git commit ──► rebuild
              cheap model     per-type      id/slug/向量合并
              (丢弃无价值)     prompt       冲突 → contradicts 待治理
```
- value_filter 与 extract 用不同模型/不同 prompt profile（sessions / wiki / docs）。
- 抽取按文档分节，单次输出 ≤6000 字符（实测截断阈值）。
- merge 幂等：同一来源片段重复提炼不产生重复节点。

### kb-api
- 检索：FTS + 向量 + 图邻接，三路融合；默认 `tier=canonical`。
- 写入：只给治理 agent 用（见 mcp-tools.md）。
- 真源操作走 git：每次写产生一个 commit，可回滚。

### mcp-server
- Streamable HTTP，挂在 `/mcp`。
- 工具即 kb-api 的薄封装；无本地状态，可多副本。

### explorer
- semantica 自带 FastAPI + React SPA，只读挂在 `/`。
- 不做编辑入口（编辑走治理 agent / CLI）。

## 4. 故障隔离（设计约束，不是建议）

1. **采集器不可用时**：知识库停在旧状态，agent 照常工作（MCP 读云端，与采集器无关）。
2. **云端不可用时**：采集器本地累积，退避重试；不阻塞本地文件读写。
3. **LLM 不可用时**：raw 片段留在队列，不丢；ingest-api 仍 200（排队的语义就是"已收到"）。
4. **提炼出错**：单文档失败不影响同批次其它文档；失败 3 次进 pending_review。
5. **磁盘水位**：daemon.json 日志上限 + `memhub-disk-guard.timer` 告警 + worker 队列上限（超过则 ingest-api 返回 1008 让客户端降级）。
   > 上一次是日志写满磁盘导致全栈清空，这条是硬性要求。

## 5. 部署形态

- Docker Compose：`ingest-api` / `worker` / `kb-api` / `mcp` / `explorer` / `nginx`（nginx 也可用宿主机的）。
- systemd timer：`rebuild.timer`（投影重建）、`disk-guard.timer`、`git-gc.timer`。
- 真源目录 `knowledge/` 挂 volume + 每日 git push 到私有远端（可选）。
- 配置与密钥：`.env`（600）+ systemd `EnvironmentFile`；不写进镜像。

## 6. 目录

```
memhub/
  src/memhub/
    contract/      # 跨端模型与枚举（对外字段的唯一实现）
    queue/         # raw_store 落盘与配额（ingest / kb 上传共用）
    ingest/        # 鉴权、游标、幂等、入队
    worker/        # value_filter / extract / merge
    kb/            # 真源读写、检索、投影重建
    mcp/           # MCP 工具
    cli/           # 运维命令
  docs/            # 架构、契约、运维
  knowledge/       # markdown 真源（git）
  prompts/         # 各 source_type 的抽取 profile
  deploy/          # compose / nginx / systemd / daemon.json
  web/             # 管理台前端
  tests/
```
