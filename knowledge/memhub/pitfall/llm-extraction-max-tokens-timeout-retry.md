---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/llm-extraction-max-tokens-timeout-retry
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- llm
- extraction
- pitfall
tier: candidate
title: LLM 抽取需处理 max_tokens 截断与超时重试
updated_at: '2026-11-18T10:56:54.868098Z'
---

逐页 LLM 结构化抽取时，max_tokens=4000 可能截断输出导致 JSON 解析失败，需要对截断与超时做重试。实际单页耗时约 30-60 秒，46 页约需 20-40 分钟，适合后台运行。
