---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/session-jsonl-mtime-cursor
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- incremental
- cursor
- session-ingest
tier: candidate
title: 会话 JSONL 增量不能按 mtime 判断，必须用字节偏移/行数游标
updated_at: '2026-11-18T10:56:54.868098Z'
---

会话文件是追加式改写，同一个活跃文件会被持续写入，因此按 mtime 或整文件哈希判断增量会导致重复抽取——一个活跃会话一天可能被全量重复抽取几十次。正确做法是在 source 上维护“上次处理到的字节偏移/行数”作为 cursor，只抽取新增段。
