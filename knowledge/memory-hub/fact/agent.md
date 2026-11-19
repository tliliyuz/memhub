---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/agent
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/会话重置与-agent-切换.md
  type: wiki
supersedes: []
tags:
- 运行时约束
- 会话
tier: canonical
title: 会话重置与 Agent 切换
updated_at: '2026-11-18T07:26:22Z'
---

> 同一会话内切换 Memory Agent 需单独发送 mem:session-reset 再重选，是记忆绑定的运行时约束。

# 定义

在 [[DSH Desktop]] 的同一会话内切换 [[Memory Agent]] 时，不能直接在 UI 上改选，必须先单独发送 `mem:session-reset` 指令，然后重新选择 Agent。

# 意义

- 说明 Agent 绑定在会话生命周期内是**粘性**的：绑定后不会因重新选择而自动重建上下文。
- 是记忆归属（[[项目记忆归属与 Agent 分配]]）在运行时的具体约束。
- 排障提示：切换后记忆读不到，先确认是否漏发 `mem:session-reset`。

# 相关实体

[[DSH Desktop]]、[[Memory Agent]]、[[项目记忆归属与 Agent 分配]]

# Citations

- `tencentdb-agent-memory-session.md`
