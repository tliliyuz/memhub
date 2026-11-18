---
confidence: 0.6
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/question/semantica-scheduling-incremental-support-unverified
kind: question
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
status: open
supersedes: []
tags:
- semantica
- scheduling
- incremental
- unverified
tier: candidate
title: semantica 原生定时调度与增量抽取支持未验证
updated_at: '2026-11-18T10:56:54.868098Z'
---

已针对 semantica 源码搜索 schedule/cron/APScheduler/celery beat 及 incremental/delta/checksum/file_hash/mtime 相关实现，但会话中未记录结论；semantica 是否原生支持定时调度与增量抽取尚未验证。
