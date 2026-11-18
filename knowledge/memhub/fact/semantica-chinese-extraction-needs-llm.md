---
confidence: 0.9
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-chinese-extraction-needs-llm
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- chinese
- ner
- extraction
tier: candidate
title: semantica 中文 pattern 抽取质量差，应使用 LLM 抽取
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 的 pattern 抽取器处理中文技术文档时，会把 "Memory Hub"、"Chat Memory" 标为 PERSON，把端口号 "8424" 标为 DATE。中文知识源应使用 --method llm 走 LLM 抽取；zh_core_web_sm 中文 spaCy 模型可作为 LLM 之外的兜底。
