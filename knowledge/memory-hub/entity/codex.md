---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: memory-hub/entity/codex
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/codex-会话导入工具.md
  type: wiki
supersedes: []
tags:
- 工具
- 导入
tier: canonical
title: Codex 会话导入工具
updated_at: '2026-11-18T07:26:22Z'
---

> 仓库自带的工具，把选定的历史 Codex 会话关联到 applesay → sdp-tag-doc 交由 Memory 提炼。

# 定义

[[TencentDB Agent Memory]] 仓库自带的 Codex 会话导入工具，用于把历史 Codex 会话导入记忆系统。

# 关键属性

- 输入：选定的历史会话（本机已有 108 个 SDP Tag 相关会话的 Markdown 导出，索引 `D:\workplace\codex-sdp-tag-sessions\README.md`）。
- 关联归属：`applesay` → `sdp-tag-doc`。
- 输出：由 Memory 提炼为 [[Chat Memory]]。
- 边界：Markdown 导出与导入 [[Chat Memory]] 是**独立操作**，不可互相替代。

# 关系

- 与 [[Codex Desktop]]：为不走 [[Memory Proxy]] 的客户端提供唯一记忆写入路径
- 与 [[Memory Agent]]：导入时指定归属
- 与 [[Chat Memory]]：导入历史 与 自动提炼 是两条独立更新路径

# Citations

- `tencentdb-agent-memory-session.md`
