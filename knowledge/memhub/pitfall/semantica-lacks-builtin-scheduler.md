---
confidence: 0.7
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/pitfall/semantica-lacks-builtin-scheduler
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- scheduling
- limitation
tier: candidate
title: Semantica 无内置定时调度器
updated_at: '2026-11-18T10:54:55.190937Z'
---

Semantica 0.7.0 源码中未发现 cron、APScheduler、celery beat 等定时调度实现；其 watch 命令基于文件系统事件监控，而非定时轮询。若需“定时抽取”，需用外部调度器（如 Windows 计划任务、cron）定时触发 semantica build/ingest 命令。
