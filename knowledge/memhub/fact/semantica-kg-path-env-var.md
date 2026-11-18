---
confidence: 0.7
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/fact/semantica-kg-path-env-var
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- configuration
- persistence
tier: candidate
title: Semantica 使用 SEMANTICA_KG_PATH 环境变量
updated_at: '2026-11-18T10:54:55.190937Z'
---

Semantica 通过环境变量 SEMANTICA_KG_PATH 指定知识图谱的持久化路径（在源码中搜索到该变量）。
