---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/semantica-cli-ingest-does-not-write-graph
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
title: semantica CLI ingest 不写图库，extract --mode all 未实现
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica 的 CLI ingest 命令不会把结果写入图库（issue #1351/#1352，作者在报错中承认），extract --mode all 也未实现。因此"目录 → 图谱"链路必须自写薄编排脚本，使用库内现成的 ContextGraph 与 build_from_entities_and_relationships API 入图。
