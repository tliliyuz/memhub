---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-ingest-only-command
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- architecture
- limitation
tier: candidate
title: semantica 只有 ingest <dir> 命令式入口，没有“源”的概念
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 提供的入库入口是命令式的 `ingest <dir>`，没有数据源（source）这一抽象，也没有多源管理、增量水位、调度能力。因此若要支持“前端多选本机路径 + 定时/监听增量抽取”，源注册表与调度器必须自研，semantica 只能作为底层图存储/抽取引擎使用。
