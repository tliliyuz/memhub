---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/anthropic-provider-base-url-env
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- anthropic
- semantica
- llm-gateway
tier: candidate
title: AnthropicProvider 不透传 base_url，但 SDK 读取 ANTHROPIC_BASE_URL
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 的 AnthropicProvider 没有 base_url 参数，但 anthropic SDK 自身会读 ANTHROPIC_BASE_URL 环境变量，因此 Anthropic 协议网关可直接接入而无需改 semantica 源码；为原型可控，也可在编排脚本里直接调用 /v1/messages 做抽取再喂给 ContextGraph。
