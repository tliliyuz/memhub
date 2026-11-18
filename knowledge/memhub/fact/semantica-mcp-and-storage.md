---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-mcp-and-storage
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
- storage
- vector-search
tier: candidate
title: semantica 具备双 MCP server 与多种图存储能力
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 提供两个 MCP server：semantica-mcp 含 17 个工具（query_graph 的 node/neighbors/search 模式、决策记录与溯源等），semantica_mcp 包含 store_document/retrieve_context 检索工具，另有 REST /build。ContextGraph 支持 save_to_file/load_from_file（JSON/Markdown），可换成 Neo4j/FalkorDB；向量库含轻量的 sqlite-vec；SEMANTICA_KG_PATH 是持久化开关。
