---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/source-registry-abstraction
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- architecture
- source-registry
- design
tier: candidate
title: 把数据源抽象成一等公民的 Source 注册表
updated_at: '2026-11-18T10:56:54.868098Z'
---

不做一次性目录配置，而是引入 Source 注册表作为自研核心：字段含 id、name、path、type（sessions/wiki/docs/...）、enabled、schedule、file_glob、cursor（增量水位）。前端提供源的 CRUD 与多选勾选，后端暴露 REST 接口（可挂在 semantica 的 /build 服务或独立薄 FastAPI）。扩展方式是新增 type（如 web 目录、git 仓库），而非改管线。
