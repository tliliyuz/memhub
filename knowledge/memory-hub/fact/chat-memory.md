---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/chat-memory
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/chat-memory.md
  type: wiki
supersedes: []
tags:
- 记忆资产
- 会话
- 记忆
- 分层
- mcp
- chat-memory
- 资产
- 记忆分层
tier: canonical
title: Chat Memory
updated_at: '2026-11-18T07:26:22Z'
---

> 会话型记忆资产，Proxy 暴露 L3/L2，Agent 按需下钻 L2 正文与 L0 原文；绑定会话满足条件时自动提炼，新证据可更新同一 L2 场景，时间流逝不触发更新；2026-11-10 起可通过 MCP 的 5 个 chat_memory_* 工具从面板只读查询（limit 上限 100，team_id 必填）。

# 定义

Chat Memory 是由**会话**产生并沉淀的会话型记忆资产，是从人与 Agent 的对话中自动提炼的隐性知识。其内部按 [[记忆分层 L0–L3]] 组织：L0 原始会话 → L1 原子记忆 → L2 场景索引 → L3 长期画像。

[[Memory Proxy]] 向 Agent 暴露 L3 长期画像与 L2 场景索引，Agent 按需下钻 L2 正文与 L0 原文，而非全量注入。会话绑定到 [[Memory Agent]] 后，满足条件时自动触发提炼；有新证据可更新同一个 L2 场景，而单纯的时间流逝不触发更新。与 [[Wiki]]、[[Skill]] 的差异见 [[三类资产模型]]。

# 意义

它是唯一「自动积累」的资产——不需要人工上传或主动整理，但代价是归属与隔离必须靠 [[项目记忆归属与 Agent 分配]] 控制。

# 使用方式

- [[Memory Proxy]] 向客户端提供 L3 长期画像与 L2 场景索引。
- Agent 按需查询：L2 正文 → L1 原子记忆 → L0 原始会话。
- 对外读取可通过会话内的 Proxy 通道，或通过 Panel 的 MCP 只读工具完成（见下文）。

# 对外读取通道

## 经 Proxy（会话内）

`memory-bridge` 端点，按 `x-conversation-id` 反推身份，仅在活跃会话内可用。

## 经 Panel（MCP，2026-11-10 起）

[[Team Brain MCP]] 提供 5 个只读工具，后端为 [[Memory Hub]]（8125）`/api/v1` + `sk-mem-` 用户密钥（`MEMORY_USER_KEY`），**可离线调用**；缺密钥时这 5 个工具返回配置指引而非报错：

| 工具 | 说明 |
| --- | --- |
| `chat_memory_agents` | 列出 agent（用于取得合法 `block_id`；**先列再拼，别手写**） |
| `chat_memory_search` | 语义检索记忆 |
| `chat_memory_layer` | 按 [[记忆分层 L0–L3]] 分层读取，`limit` 上限 100 |
| `chat_memory_list` | 列出记忆块 |
| `chat_memory_stats` | 统计信息 |

契约约束：

- `chat-memory/mine`、`chat-memory/team-assets` **必带 `team_id`**，否则 `400 MISSING_TEAM_ID`（MCP 可用 `MEMORY_TEAM_ID` 自动补齐）。
- `chat-memory/layer` 的 `limit` **上限 100**（MCP 层已 clamp）。
- `block_id` 必须是 `chat_memory-<team_id>-<agent_id>`，应由 `chat_memory_agents` 列出，别手拼。

详见 [[MCP 双后端只读接入]]。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 触发方式 | 绑定会话满足条件时自动提炼，无需上传 |
| 更新方式 | 新证据可更新同一 L2 场景；时间流逝不触发 |
| 暴露面 | L3 / L2 索引，按需下钻 |
| `modelId` 字段 | 记录**请求发出时的模型名**，非最终落地模型 |
| 归属 | 按团队 / 项目两级确定（见 [[项目记忆归属与 Agent 分配]]） |

# 更新方式

- **自动提炼**：绑定到 [[Memory Agent]] 的会话在满足条件时自动提炼。
- **导入历史**：经 [[Codex 会话导入工具]] 导入既有会话（与自动提炼是两条独立路径）。
- 新证据可以更新**同一份 L2 场景**；**时间经过本身不会触发更新**。

# 模型归因失真

`modelId` 记的是请求名，而请求名如何落到 provider 由 [[Magpie]] 的前缀 / 模糊匹配决定（见 [[模型 ID 解析与路由组]]）：

- 写 `auto/deepseek-v4.1-flash`、`group/never-stuck` 这类**路由组**：记忆里记到的是组名而非真实模型，**归因失真**。
- 需要精确归属时：使用 `provider/model` 形式的模型 id（落点确定、无兜底）。

这是“稳定性优先”与“归因精确优先”在记忆侧的直接取舍。

# 可见性与归属

- 归属由 [[项目记忆归属与 Agent 分配]] 决定；团队可见的 Chat Memory 必须分配给另一个 Agent 才能作为其运行时记忆。

# 相关实体

[[Memory Core]]（持久化落点）、[[Memory Proxy]]、[[Memory Agent]]、[[Memory Hub]]、[[Team Brain MCP]]、[[DSH Desktop]]、[[Codex Desktop]]、[[记忆分层 L0–L3]]、[[MCP 双后端只读接入]]

# 相关概念

[[记忆分层 L0–L3]]、[[记忆沉淀策略]]、[[级联代理拓扑与分层顺序]]、[[会话重置与 Agent 切换]]、[[能力开关显式固化]]、[[三类资产模型]]

# Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `memhub-magpie-级联配置手册.md`（§4.8）
- `模型-id-解析与路由组.md`
- `team-brain-mcp-接入指南.md` §1、§6、§6.3、§6.4、§6.5
