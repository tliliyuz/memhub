---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/n-2ab11ceb
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/静默失效与健康检查盲区.md
  type: wiki
supersedes: []
tags:
- 排障
- 健康检查
- 静默失效
- 故障模式
- 可观测性
- 降级
tier: canonical
title: 静默失效与健康检查盲区
updated_at: '2026-11-18T07:26:22Z'
---

> 挂载失败仍 healthy、开关关闭仍正常回复但不记记忆、Windows 入口判断失效导致 Connection closed、MCP 缺 MEMORY_USER_KEY 部分降级、skill_search 返回 0 条属正常——健康检查只探端口不校验语义，必须主动读 config.yaml、看注入日志并做真实工具调用。

# 静默失效与健康检查盲区

## 定义

「静默失效」指系统在**外部观测指标全部正常**（容器 `healthy`、`/health` 返回 200、进程存在、模型正常回复）的情况下，实际能力已经失效的故障模式。它是一类**不产生显式错误**的故障：服务进程存在、端口可连，但实际功能已失效。

「健康检查盲区」是其根因：现有健康检查**只探端口，不校验上游与配置语义**，即只验证「端口活着」，不校验「语义正确」。

共同特征是：**进程在跑、端口在听、`/health` 返回 200，但语义层面的能力已经丢失**。健康检查通常只探端口，因此这类问题不会被自动发现。

## 意义

排障成本极高——因为失败信号被掩盖。正确做法是：不信任 `/health`，而是**读配置、看日志、做真实调用**。

## 故障模式与案例集（含边界样本）

本手册实证的两个同源故障模式如下，另补充 Windows 入口、MCP 密钥类静默失效案例，以及一个容易被误判为失效的正常行为样本。

| 样本 / 现象 | 表面信号 | 真实问题 |
|---|---|---|
| 配置挂载失败（模式 A） | 容器 `healthy` | 回退 `DEFAULT_CONFIG` + 占位上游，全部请求 502，记忆注入实际不生效 |
| 能力开关缺失（模式 B） | 对话正常回复 | `.env` 生成全关闭配置，记忆不注入/不落库（见 [[能力开关显式固化]]） |
| Windows ESM 入口判断失效 | 客户端只看到 `Connection closed` | `import.meta.url === file://${argv[1]}` 永不相等，MCP 进程启动即静默退出，没有任何错误日志（见 [[Windows ESM 入口判断失效]]） |
| MCP 缺 `MEMORY_USER_KEY` | 进程正常、工具列表正常、Wiki 工具可用 | Chat Memory / Skill 工具返回配置指引（**部分降级**，不是进程故障），Wiki 与代码图谱照常可用（见 [[Team Brain MCP]]） |
| `skill_search` 搜无此词返回 0 条 | 工具调用成功、返回空列表 | BM25 分词下库里确实没有该词，**正常行为**；用 `memory`、`wiki` 等真实词才有结果 |

### A. 挂载静默失效 → 全 502

- 现象：`start-proxy.sh` 打印 `[ok] tdai-proxy healthy`，但**所有请求返回 502**。
- 根因：Git Bash 的 MSYS 路径转换把 `-v D:\path\config.yaml:/data/config.yaml` 的 `D:` 当成路径分隔符，挂载源被拼坏：

  ```
  实际 Source = D:\workplace\...\config.yaml;C:\Program Files\Git\data\config.yaml
  容器内 /data/config.yaml → No such file
  启动日志 → config not found — falling back to DEFAULT_CONFIG
  实际上游 → https://llm-upstream.example.com/v2/chat/completions（占位地址）
  ```
- 为什么难发现：健康检查只探端口，不校验上游，容器照样 `healthy`。
- 解决与自检见 [[start-proxy 启动脚本]]。

### B. 开关未显式设置 → 记忆静默失效

- 现象：服务完全正常、模型正常回复，**只是不记记忆**。
- 根因：`PROXY_ENABLE_*` 缺失导致生成全关闭配置，见 [[能力开关显式固化]]。

### C. Windows ESM 入口判断失效 → Connection closed

- 现象：客户端只看到 `Connection closed`，服务端没有可用的业务错误返回。
- 根因：`import.meta.url === file://${argv[1]}` 永不相等，MCP 进程启动即静默退出。
- 排障提示：`Connection closed` 几乎总意味着服务端**在启动阶段就退出了**，应先查入口判断与依赖加载，而不是查网络。详见 [[Windows ESM 入口判断失效]]。

### D. MCP 缺 `MEMORY_USER_KEY` → 部分能力降级

- 现象：进程正常、工具列表正常。
- 真实问题：Chat Memory / Skill 工具返回配置指引（**部分降级**），Wiki 与代码图谱照常可用。
- 注意：这类降级不会让 `/health` 或进程状态报错，必须通过真实工具调用或密钥接口校验发现；它属于**部分降级而非进程故障**，但能力确实缺失，需补齐密钥。参见 [[Team Brain MCP]]。

### E. `skill_search` 搜无此词返回 0 条 → 正常行为，非失效

- 现象：工具调用成功、返回空列表。
- 真实状态：BM25 分词下库里确实没有该词，**正常行为**；用 `memory`、`wiki` 等真实词才有结果。
- 注意：不要把「返回 0 条」误判为静默失效；应先用已知存在的词做对照调用。

## 如何消除盲区

盲区的本质是「检查项与能力项不对齐」。对策是把检查下沉到语义层，主动读配置与日志：

| 检查对象 | 命令 | 判据 |
|---|---|---|
| 挂载是否生效 | `docker exec tdai-proxy head -5 /data/config.yaml` | 能读到内容 |
| 挂载源是否被拼坏 | `docker inspect tdai-proxy` | `Mounts.Source` 形如 `/d/workplace/...` |
| 上游是否正确 | `head -12 /data/config.yaml` | `upstream.url = http://host.docker.internal:3425/v1` |
| 能力开关 | 同上 | 四项 `enabled: true` |
| 注入管线 | `docker logs tdai-proxy --tail 100 \| Select-String 'injection.pipeline.done'` | `errorCount=0` |
| 记忆是否在涨 | 面板 `POST /api/v1/chat-memory/layer` | L0/L1 的 `total` 增长 |

### 三层验证范式

[[Team Brain MCP]] 的接入验证给出了一套可复用的分层检查顺序：

1. **后端健康**：`curl http://127.0.0.1:8424/health`、`curl http://127.0.0.1:8125/health` —— 只能排除「服务没起」
2. **面板鉴权**：`POST /api/v1/chat-memory/mine`，带 `x-tdai-service-id`、`x-tdai-user-key` 与 `{"team_id":"team-xxxx"}` —— 验证密钥与归属是否真的有效
3. **MCP 层断言**：`test-client.mjs` 的 12 项断言（19 工具存在性、双后端真实调用、无密钥降级行为），实测 12/12 通过 —— 这才是语义层的验证

关键洞察：**第 1 层通过不代表第 2、3 层通过**；反过来，第 3 层的「降级返回指引」也不该被当成故障。

### 补充判据与方法

- 不要以 `/health` 200 或「进程存在」作为功能正常的证据。
- 主动读 `config.yaml`（是否被生成脚本覆盖）、看注入日志、做一次**真实工具调用**。
- 对 [[Team Brain MCP]]：`/health` 只能证明 8424 / 8125 端口活着；`sk-mem-` 密钥是否有效必须靠 `POST /api/v1/chat-memory/mine` 或 `test-client.mjs` 的 12 项断言才能发现。
- 对客户端侧：`Connection closed` 几乎总意味着服务端**在启动阶段就退出了**，应先查入口判断与依赖加载，而不是查网络。
- 对 `skill_search`：返回 0 条不一定代表失效，先用 `memory`、`wiki` 等已知真实词做对照，排除「库里确实没有该词」的正常情况。

## 与其他页面的关系

- 与 [[Proxy 转发故障分段定位]] 互为排障分支：本页模式 A 是**配置挂载段**的 502 根因，后者是 **Proxy→上游段**的 502 根因，二者不可合并成一条结论。
- 模式 B 的具体成因见 [[能力开关显式固化]]。
- Windows 入口问题见 [[Windows ESM 入口判断失效]]。
- 验证顺序见 [[级联代理拓扑与分层顺序]] 的五步清单。
- 相关实体与页面：[[Memory Proxy]]、[[Team Brain MCP]]、[[Memory Hub]]、[[Memory Knowledge]]、[[MCP 双后端只读接入]]。
- [[MCP 双后端只读接入]] —— 无密钥部分降级的结构性成因。
- [[凭据分层模型]] —— `MEMORY_USER_KEY` 缺失时的行为边界。
- [[stdio MCP 分发与启动约束]] —— 启动失败没有 `/health` 可探。
- [[Team Brain MCP]] —— 三层验证的载体。

## 常见话题

- 部署模型与健康检查设计
- 排障方法论：从「端口活着」到「语义正确」

## Citations

- `memhub-magpie-级联配置手册.md` §4.1、§4.3、§5
- `memory-hub-magpie-级联配置手册.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §2、§5、§6.1、§6.2
