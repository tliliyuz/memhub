---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/procedure/semantica-kb-builder-prototype-flow
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- procedure
- prototype
tier: candidate
title: semantica 知识库原型链路
updated_at: '2026-11-18T10:56:54.868098Z'
---

已验证的原型链路：目录扫描 → 内容哈希增量判断 → LLM 结构化抽取（直接调 Anthropic 协议 /v1/messages）→ ContextGraph 入图 → 持久化 kg.json → semantica-mcp 通过 SEMANTICA_KG_PATH 挂载读取。首个页面 code-graph.md 抽出 21 个实体、31 条关系，图谱 17KB。
