---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/two-layer-ingest-interfaces
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- architecture
- ingest
- interface
tier: candidate
title: 入库分两层接口：历史知识源批量接口 + 会话自动提取接口
updated_at: '2026-11-18T10:56:54.868098Z'
---

两套入口共用同一套 source 注册表 + 调度器 + 抽取管线，差异只用 type 决定三件事：文件解析方式、prompt profile、触发策略。1) 历史知识源接口（一次性批量）：上传文件或选本机目录，整页抽取、document prompt profile、无水位、跑完即止，用于冷启动和偶尔灌外部资料；2) 会话自动提取接口（持续增量，重心）：前端多选本机路径（如 Claude Code sessions、Codex sessions），游标增量→价值筛选→提炼→归并，session prompt profile，静默 N 小时后触发。
