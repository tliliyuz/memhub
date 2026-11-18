---
confidence: 0.8
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/fact/semantica-supports-custom-llm-base-url
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- llm
- openai
- deepseek
tier: candidate
title: Semantica 支持自定义 LLM base_url
updated_at: '2026-11-18T10:54:55.190937Z'
---

Semantica 的 OpenAI LLM provider（semantica/llms/openai.py）支持传入自定义 base_url，可对接兼容 OpenAI API 的服务（如 DeepSeek）。代码中也有 deepseek provider。
