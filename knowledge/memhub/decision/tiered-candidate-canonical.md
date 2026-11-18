---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/tiered-candidate-canonical
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- quality
- review
- tier
- governance
tier: candidate
title: 图谱知识分层 candidate / canonical，默认只信 canonical
updated_at: '2026-11-18T10:56:54.868098Z'
---

手工 wiki 有人工判断做闸门，自动提炼没有，因此节点带分层字段：抽取结果先进 tier=candidate，在 explorer 的人工复核队列中确认后升 tier=canonical。检索默认只信 canonical，candidate 仅在无 canonical 命中时兜底。否则长期运行后图谱会堆积同义重复与过时事实（semantica 自带的冲突检测只能标红，不能替人裁决）。
