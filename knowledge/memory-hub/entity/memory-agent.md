---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: memory-hub/entity/memory-agent
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/memory-agent.md
  type: wiki
supersedes: []
tags:
- 角色
- 记忆组织
tier: canonical
title: Memory Agent
updated_at: '2026-11-18T07:26:22Z'
---

> 决定"读哪份记忆、沉淀哪份记忆"的执行侧代理，按团队/项目维度分配与隔离记忆。

# 定义

Memory Agent 是记忆的执行侧代理：实际执行任务的是 [[DSH Desktop]] 或 [[Codex Desktop]]，而 Memory Agent 决定读取哪份记忆、把新经验沉淀到哪份记忆。

# 关键属性

- 按 **团队 → 项目** 两级归属记忆（本环境为 `applesay` → `sdp-tag-doc`）。
- 同一项目的开发、排障、评测可以共用一个 Agent；需要隔离记忆时才拆分。
- 团队可见的 [[Chat Memory]] 必须分配给另一个 Agent，才能作为该 Agent 的运行时记忆使用。
- 绑定发生在会话初始化时（DSH 表单选择 `applesay` → `sdp-tag-doc`）或会话导入时（Codex 导入工具关联同一归属）。

# 关系

- 与 [[项目记忆归属与 Agent 分配]]：分配与隔离规则的载体
- 与 [[applesay 团队]]、[[SDP Tag 项目]]：归属实体
- 与 [[DSH Desktop]]：会话绑定 + 自动归档
- 与 [[会话重置与 Agent 切换]]：切换需 `mem:session-reset` 后重选
- 与 [[Codex 会话导入工具]]：导入时指定归属
- 与 [[记忆沉淀策略]]：决定沉淀什么（隐性知识优先）

# Citations

- `tencentdb-agent-memory-session.md`
