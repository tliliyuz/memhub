---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/adopt-semantica-as-kb-base
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- architecture
- decision
tier: candidate
title: 采用 semantica 作为知识库底座，自研薄编排层
updated_at: '2026-11-18T10:56:54.868098Z'
---

评估后决定以 semantica 作为知识库底座，由它承担解析、分块、去重、溯源、图谱存储、MCP 协议与向量检索；自研部分仅限目录扫描 + LLM 提示词 + 入图，约 200 行 Python。否决了完全自研整条链路的方案，理由是 semantica 覆盖了大部分重活且 API 足够。
