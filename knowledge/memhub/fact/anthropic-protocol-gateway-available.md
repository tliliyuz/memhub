---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/anthropic-protocol-gateway-available
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- llm-gateway
- anthropic
- environment
tier: candidate
title: 配置的 Anthropic 协议网关 /v1/messages 可用
updated_at: '2026-11-18T10:56:54.868098Z'
---

环境中 ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN 指向的网关支持 Anthropic messages 协议，/v1/messages 实测返回 200；但需去掉 NO_PROXY 后 httpx 才能连通，直连 curl 可能不可达。
