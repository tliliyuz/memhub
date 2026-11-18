---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/preference/focus-on-session-auto-extraction
kind: preference
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- preference
- priority
- session-ingest
tier: candidate
title: 系统重心放在会话自动提取链路，而非手工知识导入
updated_at: '2026-11-18T10:56:54.868098Z'
---

该系统的目的是让人不再手动导出 wiki 或其他知识，因此建设重心是会话自动提取提炼接口（多选本机路径如 claudecode/codex 会话目录，抽取当日新增会话内容入图）；历史知识源接口只作为已有知识上传的辅助入口。抽取出的知识类型（事实、决策、procedure、pitfall 等）用固定枚举表达，而非分成割裂的两套结构。
