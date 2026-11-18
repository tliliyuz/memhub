---
confidence: 0.8
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/fact/semantica-cli-mcp-rest-interfaces
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- mcp
- cli
- rest-api
tier: candidate
title: Semantica 提供 CLI、MCP 和 REST 接口
updated_at: '2026-11-18T10:54:55.190937Z'
---

Semantica 的 CLI 包含 watch、build、ingest、store、info 等命令；同时提供 MCP server（semantica_mcp）和 REST API server（semantica/server.py），可供 agent 通过接口查询知识库。
