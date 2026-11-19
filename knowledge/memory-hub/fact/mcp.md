---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/mcp
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/mcp-双后端只读接入.md
  type: wiki
supersedes: []
tags:
- mcp
- 架构
- 双后端
- 只读
- 鉴权
- 降级
tier: canonical
title: MCP 双后端只读接入
updated_at: '2026-11-18T07:26:22Z'
---

> 按「调用是否需要业务身份」把 MCP 的 19 个工具拆到两个后端：Wiki/代码图谱走 Knowledge 8424 的 /v3 免密钥端点，Chat Memory/Skill 走面板 8125 + sk-mem 用户密钥；8096 的 bridge 因会话耦合被排除。

# MCP 双后端只读接入

## Definition（定义）

[[Team Brain MCP]] 不采用单一接口聚合，而是按「**这次调用是否需要用户身份 / 业务身份**」把 19 个工具拆到两个后端：

| 后端 | 端点 | 鉴权 | 承载工具 |
|---|---|---|---|
| [[Memory Knowledge]]（8424） | `/v3` 只读端点 + `/health` | **无需密钥** | [[Wiki]] 4 个、[[Code Graph]] 8 个 |
| [[Memory Hub]] 面板（8125） | `/api/v1/*` | `x-tdai-user-key`（`sk-mem-...`）+ `x-tdai-service-id` | [[Chat Memory]] 5 个、[[Skill]] 2 个 |

两个后端共享底层存储 [[Memory Core]]（8420），最终都落到 8420。

## Significance（意义）

这层设计决定了三件事：可用性分档、凭据边界具体化、以及为什么不能用 8096。下面分别展开，并补充只读边界与模型链路的分离。

### 1. 8096 的 bridge 端点被排除

[[Memory Proxy]]（8096）的 `memory-bridge` / `skill-bridge` **在 MCP 场景不可用**：

- 它们从 `x-conversation-id` **反推调用者身份**，只有在活跃 DSH 会话内才成立；
- 脱离会话的离线 MCP 调用一律返回 `40101 session not initialized`；
- 而 MCP server 是任意 agent 拉起的独立子进程，**没有会话上下文**。

所以 Chat Memory 与 Skill 改走面板 API（8125），用用户密钥鉴权，可离线调用。这是「会话耦合的鉴权方式无法服务无会话进程」的直接案例。它也是「双后端」的直接成因，并修正了一个隐含假设：**Proxy 不是所有读取路径的必经点**。

### 2. 只读边界与模型链路分离

- 写操作（建 wiki / 删除 / ingest / 分配记忆）**不暴露**给 MCP，仍归控制面，避免 agent 误改。理由：agent 是高频、非确定性的调用方，写能力一旦暴露，误改成本远大于收益。
- 工具面与 [[三类资产模型]] 的四类资产一一对应，见 [[Team Brain MCP]] 的工具清单。
- MCP **不参与模型转发**：检索链是 `Agent → MCP → 8424/8125 → 8420`，模型链是 `Agent → 8096 Proxy → 3425 Magpie`，两条路径**平行**（见 [[级联代理拓扑与分层顺序]]）。

### 3. 无密钥降级（partial degradation）

缺 `MEMORY_USER_KEY` 时进程不崩溃，而是让 Chat Memory / Skill 工具返回配置指引，Wiki 与代码图谱照常可用。这是一种「**部分可用**」的降级契约，也就是可用性分档：不是整体不可用，而是部分降级。

代价是**故障不会以启动失败的形式暴露**——与 [[静默失效与健康检查盲区]] 中的同类现象一致：`/health` 只能证明端口活着，用户密钥是否有效必须靠真实工具调用才能发现。

### 4. 凭据层面的含义

`sk-mem-` 用户密钥经 `MEMORY_USER_KEY` 下发到 MCP 进程 env，可以下发到客户端，因为它只授权**面板只读查询**；上游模型凭据仍只留在服务端。这正是 [[凭据分层模型]] 主张的两段式信任边界。

## 调用约束（工具面）

| 约束 | 表现 | 处理 |
|---|---|---|
| `team_id` 必填 | `chat-memory/mine`、`team-assets` 漏传 → `400 MISSING_TEAM_ID` | `MEMORY_TEAM_ID` 自动补齐，见 [[项目记忆归属与 Agent 分配]] |
| `limit ≤ 100` | `chat-memory/layer` 传 200 → 400 | MCP 层已 clamp，见 [[记忆分层 L0–L3]] |
| `block_id` 格式固定 | 必须 `chat_memory-<team_id>-<agent_id>` | 先用 `chat_memory_agents` 列出 |
| 主键禁用空格/特殊字符 | — | 见上 |

## Related Entities / 相关概念

[[Team Brain MCP]] · [[Memory Knowledge]] · [[Memory Hub]] · [[Memory Proxy]] · [[Memory Core]] · [[Code Graph]] · [[Wiki]] · [[Chat Memory]] · [[Skill]] · [[三类资产模型]] · [[项目记忆归属与 Agent 分配]] · [[记忆分层 L0–L3]]

- [[DSH Cordis 插件式 MCP 接入]] —— 客户端侧的接入方式
- [[stdio MCP 分发与启动约束]] —— 进程侧的启动前提
- [[级联代理拓扑与分层顺序]] —— 检索链平行于模型链，不经 8096

## Common Topics

- 系统架构：只读检索层与模型转发层的分层
- 权限模型：免密钥只读端点 vs 用户密钥鉴权端点
- 数据流：`Agent → MCP → {8424,8125} → 8420`
- 部署模型：MCP 为客户端子进程，回连 127.0.0.1（见 [[本地部署拓扑与回环绑定]]）
- 失效模式：会话耦合（`40101`）、无密钥部分降级、Windows 入口判断失效

## Citations

- `team-brain-mcp-接入指南.md` 第 1、2、7 节
