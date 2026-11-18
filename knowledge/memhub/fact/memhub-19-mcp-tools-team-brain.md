---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/memhub-19-mcp-tools-team-brain
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- mcp
- memhub
- compatibility
tier: candidate
title: memhub 上挂着 19 个 Team Brain MCP 工具
updated_at: '2026-11-18T10:56:54.868098Z'
---

memhub 上现有 19 个 MCP 工具（Team Brain MCP），Claude Code、Codex、DSH 的配置都指向该 endpoint。替换 memhub 时若不同步实现相同的工具名与契约、或提供适配层，切换当天所有 agent 的读写链路会中断。
