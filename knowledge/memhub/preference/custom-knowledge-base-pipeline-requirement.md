---
confidence: 0.9
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/preference/custom-knowledge-base-pipeline-requirement
kind: preference
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- requirements
- knowledge-base
- pipeline
tier: candidate
title: 定制化知识库链路需求
updated_at: '2026-11-18T10:54:55.190937Z'
---

用户期望的链路：人工选择数据源目录 → AI 定时抽取、清洗、结构化并存入知识库 → 系统提供 MCP/CLI 接口 → agent 通过接口读取数据。本质是带自动沉淀入库功能的定制化知识库。
