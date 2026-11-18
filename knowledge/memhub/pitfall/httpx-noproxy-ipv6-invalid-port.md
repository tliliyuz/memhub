---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/httpx-noproxy-ipv6-invalid-port
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- httpx
- proxy
- windows
- pitfall
tier: candidate
title: NO_PROXY 含 IPv6 方括号会导致 httpx URL 解析报错
updated_at: '2026-11-18T10:56:54.868098Z'
---

当环境变量 NO_PROXY 含 "[::1]" 时，httpx 会报 "Invalid port: ':1]'"。规避方式是在 import httpx 之前从 os.environ 中 pop 掉 NO_PROXY 与 no_proxy。
