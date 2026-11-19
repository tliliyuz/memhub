---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-0-7-0-capabilities
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- knowledge-base
- tooling
tier: candidate
title: semantica 0.7.0 的模块与接口能力
updated_at: '2026-11-19T06:28:05.514804Z'
---

semantica 0.7.0 的 Python 包包含 semantica CLI（build、ingest、watch、store 等命令）、MCP server、REST server，以及 ingest/pipeline/kg/vector_store/graph_store 等模块；LLM 提供商包含 OpenAI 与 DeepSeek；可通过 pip 安装，extras 包括 watch、vectorstore-sqlite、documents。
