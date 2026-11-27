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
 │   /mcp              → kb-api (MCP, streamable HTTP)                     │
 │   /                → kb-api（管理台 SPA，GitHub 登录后）                  │
 ├─────────────────────────────────────────────────────────────────────────┤
 │  ingest-api → 正文: ClickHouse memhub_raw.raw_sessions（180 天 TTL）     │
 │           → 队列/游标/设备: PostgreSQL memhub_prod（ingest_queue 等）    │
 │  kb-api(上传) → ingest /internal/enqueue（不直连队列或 CH）              │
 │  worker:  value_filter(cheap) → extract(expensive) → merge              │
 │  merge → PostgreSQL 知识真源 kb_* (schema kb)                             │
 │  memory-aggregate（周任务）→ kb_memory_* → 已发布快照 → 会话抽取注入       │
 │  检索：应用层 BM25（向量混合按 ADR-0007 另案）                             │
 └─────────────────────────────────────────────────────────────────────────┘
           ▲
           │ 读取 / 受权写候选
 ┌─────────┴──────────────┐
 │ 多台机器上的 agent      │  ← MCP / CLI，走 memhub.work，不经任何本地代理
 └────────────────────────┘
```

## 2. 与旧 memhub 的关键差异

| 旧 | 新 |
|---|---|
| Memory Proxy 在模型请求路径上 | 请求路径上没有 memhub；模型直连 Magpie |
| 记忆失败 = 模型不可用 | 采集/提炼失败只影响记忆新鲜度，用户正常工作 |
| Team Brain MCP 本地进程 + 共享 key | 远端 `/mcp`，每条凭据限定库范围与读写作用域；吊销靠改配置重启 |
| 会话靠 Proxy 旁路抓取 | collector 直接读本地 session 文件，游标增量 |
| 状态散在 Proxy/本地 relay | 状态只在云端（PG 队列 + CH 原文 + 游标 + 知识库表） |
| 数据格式即实现 | PostgreSQL `kb_*` 真源（markdown 仅一次性迁移源）；图谱与检索直接查询，不落文件投影 |

## 3. 组件职责

### collector（客户端，e4 负责）
- 读 `sources.json`；按 interval 扫描；按 `GET /ingest/cursor` 对齐。
- 只做字节搬运：切增量、算 sha256、打包、压缩、推送、落本地 state。
- **不做**任何解析、抽取、判断。无 UI（配置由桌面端写入），systemd/launchd/计划任务托管。
- 崩溃恢复：state 文件原子写；未确认批次重推（服务端按 batch_id 幂等）。

### ingest-api（服务端）
- 先验证设备凭据，再检查显式目标：`kb_projects` 存在该行且 `archived_at` 为空（只读，不写知识真源）；通过后才可能写正文、入队或推进游标。
- 正文写 ClickHouse `memhub_raw.raw_sessions`（gzip HTTP，`(project, sha256)` 去重，180 天 TTL）；队列行写 PG `ingest_queue`（主键 `(project, sha256)`），两者在同一请求内完成，正文先于队列行。
- 只做校验与入队，不做 LLM 调用，响应 <200ms。

### queue（跨模块队列与正文计量，非独立进程）
- `memhub.queue.content`：正文存储（生产 ClickHouse，dev/test 本地目录）；`memhub.queue.tasks`：PG `ingest_queue` 的领取、租约、重试、终态与批次进度。
- 写入方：ingest-api 的 `/ingest/raw`、管理台上传（经 ingest `/internal/enqueue`）；读取方只有 worker。
- `MEMHUB_QUEUE_MAX_BYTES` 按 `queued + processing` 行的 `size` 求和；判重与配额都只看队列主键，不再维护第二份 `seen_shas`。
- 放在 `queue/` 而不是 `ingest/`：上传入口不该依赖采集协议层（鉴权、游标、<200ms 约束）；鉴权、游标校验与错误码映射留在各自路由层，这里只做与协议无关的存储与计量。

### worker（服务端，单机串行 + 少量并发）
- 用 `FOR UPDATE SKIP LOCKED` 领取队列行并带租约；先确认队列身份和目标授权，再按 `(project, sha256)` 从 ClickHouse 取正文。明确不合规或正文缺失的队列行隔离，暂不能核验时退回队列且不消耗失败次数。管理台凭据不与设备授权混用。
- 会话只从有出处的对话提炼候选，允许零结果；文档和 wiki 继续走文档提炼管线。合并直接写 PG `kb_*` 表（一次写入 = 一个事务），不再落 markdown。
- 会话抽取注入已发布的长期记忆（ADR-0016）：worker 启动时固定一个快照版本，按 BM25 取 top-k 并受字符预算约束，`extract_session` 审计记录版本；手工 `memhub ingest --profile sessions` 走同一口径。记忆只作判断与归一化准则，不能充当逐字证据。
- 长期记忆由独立命令 `memhub memory-aggregate` 周期聚合跨项目 canonical 节点，产出条目/候选并发布快照；worker 的抽取路径不写记忆，也不把记忆当模型输入。

### kb-api
- 管理台：`memhub kb` 在同一进程托管打包前端，`/` 由 nginx 反代；页面直接调 `/api/v1/kb/*`，没有 explorer 子进程，也没有文件投影。
- 检索：按授权范围与 `kind` 过滤后，应用层 BM25 排序；默认排除 `deprecated`（`tier=canonical`），`tier=all` 才包含废弃节点。向量混合检索按 ADR-0007 另案推进。
- 写入：只给治理 agent 用（见 mcp-tools.md）；写操作落 `kb_*` 表并在同一事务追加修订历史。
- 上传：`/api/v1/kb/uploads` 校验文件后调用 ingest 的内部接口 `/internal/enqueue`，由 worker 按 docs profile 提炼，不经过采集协议；kb-api 不持有队列、ClickHouse 或本机 raw 目录（见 [kb-admin-api.md](contracts/kb-admin-api.md) §4.7）。
- 长期记忆：`/api/v1/kb/memories*` 提供条目、候选与快照的查询和治理动作，管理台「长期记忆」页只展示元数据与结论；会话抽取的注入不经过该入口。
- 备份与回滚：`pg_dump` 为唯一完整备份；单节点回滚走 `kb_node_revisions` 的完整快照，不再用 git。

### mcp-server（首版随 kb-api 进程）
- 由 kb-api 在精确 `/mcp` 提供无状态 Streamable HTTP，协议解析交给官方 MCP Python SDK；配置了 MCP 凭据才启用，未配置时直接返回 404，不落到管理台。
- 授权库范围与读写作用域按请求注入。写工具直接创建 `canonical` 节点（ADR-0014），复用 PG 写作用域（事务级 advisory lock）和 `kb_projects` 活动库校验；更新与废弃仅限节点创建者本人。
- 独立进程与多副本形态尚未实现；拆分需先改本节与 §5 的部署形态。

## 4. 故障隔离（设计约束，不是建议）

1. **采集器不可用时**：知识库停在旧状态，agent 照常工作（MCP 读云端，与采集器无关）。
2. **云端不可用时**：采集器本地累积，退避重试；不阻塞本地文件读写。
3. **LLM 不可用时**：队列行留在 PG、正文留在 CH，不丢；ingest-api 仍 200（排队的语义就是"已收到"）。
4. **提炼出错**：单文档失败不影响同批次其它文档；失败 3 次进 pending_review。
5. **磁盘水位**：daemon.json 日志上限 + `memhub-disk-guard.timer` 告警 + 队列上限（超过则 ingest-api 返回 1008、管理台上传返回 1013）。原文不占本机数据盘。
   > 上一次是日志写满磁盘导致全栈清空，这条是硬性要求。

## 5. 部署形态

- Docker Compose：`ingest-api` / `worker` / `kb-api` / `nginx`（nginx 也可用宿主机的）；`/mcp` 由
  kb-api 进程提供，不单列服务。
- systemd timer：`disk-guard.timer`、`memory-aggregate.timer`（每周聚合并发布长期记忆快照）；知识库备份由部署侧定时 `pg_dump` 承担。
- 知识真源在 PostgreSQL（`memhub_prod` 的 `kb` schema），随实例备份；`knowledge/` 只作为一次性迁移源，迁移校验通过后从服务器删除。
- 配置与密钥：`.env`（600）+ systemd `EnvironmentFile`；不写进镜像。

## 6. 目录

```
memhub/
  src/memhub/
    contract/      # 跨端模型与枚举（对外字段的唯一实现）
    queue/         # CH 正文存储 + PG 队列、配额（ingest / worker / 上传共用）
    ingest/        # 鉴权、游标、幂等、正文入 CH、队列入 PG
    worker/        # value_filter / extract / merge
    kb/            # 真源读写（PG kb_*）、检索、管理台 API
    mcp/           # MCP 工具
    cli/           # 运维命令
  docs/            # 架构、契约、运维
  knowledge/       # markdown 一次性迁移源（迁移完成后从服务器删除；仓库只留测试夹具）
  alembic/         # kb_* 表的 DDL 迁移
  prompts/         # 各 source_type 的抽取 profile
  deploy/          # compose / nginx / systemd / daemon.json
  web/             # 管理台前端
  tests/
```
