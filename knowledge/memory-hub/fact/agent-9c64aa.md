---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/agent-9c64aa
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/项目记忆归属与-agent-分配.md
  type: wiki
supersedes: []
tags:
- 权限模型
- 记忆组织
- 记忆归属
- team_id
- block_id
- agent
tier: canonical
title: 项目记忆归属与 Agent 分配
updated_at: '2026-11-18T07:26:22Z'
---

> 以“团队 → 项目”两级确定记忆归属；同项目开发/排障/评测可共用一个 Agent，需要隔离时才拆分，团队可见的 Chat Memory 必须分配给另一个 Agent。MCP 工具面上 team_id 必填（漏传 400 MISSING_TEAM_ID），block_id 形如 chat_memory-<team_id>-<agent_id>。

# 定义

记忆归属采用**两级命名空间**：团队 → 项目（例：`applesay` → `sdp-tag-doc`）。[[Memory Agent]] 依据该归属决定读取与沉淀哪份记忆（读哪份记忆、沉淀哪份记忆）。

# 分配规则

- 同一项目的 **开发、排障、评测可共用一个 Memory Agent**。
- 只有在**需要隔离记忆**时才拆分 Agent。
- **团队可见的 [[Chat Memory]] 必须分配给另一个 Agent**，才能作为该 Agent 的运行时记忆使用（可见 ≠ 自动成为运行时上下文）。

# MCP 工具面上的归属标识（2026-11-10 补充）

| 标识 | 形式 | 约束 |
|---|---|---|
| `team_id` | 团队标识 | **必填**。`chat-memory/mine` 与 `team-assets` 漏传直接 `400 MISSING_TEAM_ID` |
| `MEMORY_TEAM_ID` | [[Team Brain MCP]] 的环境变量 | 配好后工具调用可省略 `team_id`，由 server 自动补齐 |
| `block_id` | `chat_memory-<team_id>-<agent_id>` | 格式固定，**不要手拼**——先用 `chat_memory_agents` 工具列出 |

`block_id` 是把「归属」编码进主键的对外可读形式：团队 + Agent 两段就唯一确定一条记忆块。

# 意义

- 归属即隔离边界：避免不同项目/不同可见性范围的记忆互相污染。
- 归属是隔离与可见性的唯一开关。归属错了，读到的就是别人的记忆，或者干脆读不到。
- 绑定时机：[[DSH Desktop]] 新开会话的初始化表单、[[Codex 会话导入工具]] 的关联选择。
- 运行时约束：同会话切换 Agent 需先发 `mem:session-reset` → 见 [[会话重置与 Agent 切换]]。

# 相关实体

[[Memory Agent]]、[[applesay 团队]]、[[SDP Tag 项目]]、[[DSH Desktop]]、[[Codex 会话导入工具]]、[[Team Brain MCP]]

# 相关概念

- [[三种工具读取路径]] → 见 [[MCP 双后端只读接入]]（Chat Memory 工具的后端与鉴权）
- [[记忆分层 L0–L3]] —— 归属确定后再选层与 `limit`
- [[会话重置与 Agent 切换]] —— 运行时切换 Agent 的约束

# Citations

- `tencentdb-agent-memory-session.md`
- `team-brain-mcp-接入指南.md` 第 6.3、6.5 节
