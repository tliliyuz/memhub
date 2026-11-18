---
confidence: 0.9
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/preference/custom-knowledge-base-pipeline-requirements
kind: preference
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- knowledge-base
- requirements
- mcp
- cli
tier: candidate
title: 定制化知识库链路的功能要求
updated_at: '2026-11-18T10:56:54.868098Z'
---

目标链路要求：人工选择数据源目录；AI 定时从目录抽取数据、清洗、结构化并存入知识库；系统提供 MCP/CLI 接口供 agent 读取数据；具备自动沉淀入库能力。
