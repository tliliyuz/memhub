---
confidence: 0.9
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/procedure/install-semantica-with-extras
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- installation
- pip
tier: candidate
title: 安装 Semantica 并验证
updated_at: '2026-11-18T10:54:55.190937Z'
---

在 Windows 上可通过 `pip install "semantica[watch,vectorstore-sqlite,documents]"` 安装 Semantica 0.7.0，extras 包括 watch（文件监控）、vectorstore-sqlite（SQLite 向量存储）、documents（文档解析）。安装后可用 `semantica --version` 和 `semantica info` 验证。
