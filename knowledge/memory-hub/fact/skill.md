---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/skill
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/skill.md
  type: wiki
supersedes: []
tags:
- skill
- 资产
- 操作流程
- 记忆资产
- mcp
- 检索
tier: canonical
title: Skill
updated_at: '2026-11-18T07:26:22Z'
---

> 可复用操作流程资产：Proxy 提供可用列表、Agent 用到时读全文，可从会话中提炼；2026-11-10 起也可经面板 API 用 skill_search / skill_read 只读获取（BM25 检索，返回 0 条常属正常）。

# 定义

Skill 是可复用的**操作流程**资产。粒度是"可重复执行的排查、验证或操作流程"：一段已验证的排查、验证或操作流程，Agent 在需要时按其执行，而不是从零推导。适用于可重复的流程类知识。

与 [[Wiki]] 的区别是「可执行的操作步骤」而非「可阅读的文档」。

# 意义

Skill 把「一次验证过的方法」固化成可重复动作，是 [[记忆沉淀策略]] 中「已证明有效的操作方法」这类隐性知识的载体。

# 定位

- 与 [[Chat Memory]]（会话沉淀）和 [[Wiki]]（文档知识）互补，构成[[三类资产模型]]。
- 整体定位见 [[三类资产模型]]。

# 使用方式

- [[Memory Proxy]] 向客户端提供可用 Skill 列表。
- Agent 在用到时读取完整步骤全文。
- 可从会话中提炼，也可显式维护。

# 读取通道

| 通道 | 后端 | 条件 |
|---|---|---|
| Proxy 可用列表 | [[Memory Proxy]]（8096） | 需活跃会话（`x-conversation-id`）；离线场景返回 `40101` |
| MCP 只读 | [[Team Brain MCP]] → [[Memory Hub]] 8125 `/api/v1` + `sk-mem-` 密钥 | 可离线 |

对外工具：

- `skill_search`：按关键词检索 Skill，使用 **BM25 分词**。搜不到的词（如「级联」）返回 0 条**不是故障**（库里确实没有该词）；使用 `memory`、`wiki` 这类真实存在的词才有结果。返回 0 条不是故障，见 [[静默失效与健康检查盲区]]。
- `skill_read`：读取 Skill 全文。

结论：Skill 的**可用列表来源从 Proxy 扩展到 Panel**（[[Memory Hub]]，8125），读取不再要求活跃会话（见 [[MCP 双后端只读接入]]）。2026-11-10 起也可经面板 API 用 `skill_search` / `skill_read` 只读获取。

# 更新方式

- 可从会话中提炼（与 [[Chat Memory]] 同源，但以流程为单位）。
- 也可显式维护。

# 信息状态

早期源文档关于 Skill 仅两句描述，页面内容有限；后续来源（`team-brain-mcp-接入指南.md` 第 1、6.2 节）补充了对外读取接口、MCP 只读接入、BM25 检索行为与「返回 0 条不是故障」的说明。详细机制仍待后续来源补充。

# 相关实体

[[Memory Proxy]]、[[Chat Memory]]、[[Wiki]]、[[Memory Agent]]、[[Team Brain MCP]]、[[Memory Hub]]、[[MCP 双后端只读接入]]、[[三类资产模型]]、[[记忆沉淀策略]]、[[静默失效与健康检查盲区]]

# Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §1、§6.2
