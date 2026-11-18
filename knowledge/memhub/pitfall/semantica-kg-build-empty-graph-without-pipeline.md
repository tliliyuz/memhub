---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/semantica-kg-build-empty-graph-without-pipeline
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- cli
- pitfall
tier: candidate
title: semantica kg build 无 pipeline 配置会静默产出空图
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 的 kg build 在不带 pipeline 配置时会静默产出空图（CLI 已有防护报错）。需要显式提供 pipeline 配置，或改为自行编排抽取与入图流程。
