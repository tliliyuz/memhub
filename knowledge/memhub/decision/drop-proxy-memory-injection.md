---
confidence: 0.75
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/drop-proxy-memory-injection
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- proxy
- memhub
- magpie
- architecture
tier: candidate
title: 放弃 Proxy 式会话提取与记忆注入
updated_at: '2026-11-18T10:56:54.868098Z'
---

采用 Proxy 形式提取会话、主动注入记忆会带来严重遗留问题：memhub 上云后与 magpie 的兼容问题大量源于此。结论是本质上不应该用 Proxy 这种形式去提取会话，新系统改为基于文件/源注册表的抽取入库 + MCP 拉取式读取。
