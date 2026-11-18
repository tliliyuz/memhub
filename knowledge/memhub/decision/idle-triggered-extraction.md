---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/idle-triggered-extraction
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- scheduling
- session-ingest
- design
tier: candidate
title: 会话抽取的触发时机用“静默 N 小时”而非整点 cron
updated_at: '2026-11-18T10:56:54.868098Z'
---

会话进行中就抽取会抽到半截内容，产生残缺知识。触发策略采用文件静默（mtime 在 N 小时内不再变化）后触发，而不是固定整点定时；对追加式会话文件而言，监听+静默判断比 cron 更贴合实际。
