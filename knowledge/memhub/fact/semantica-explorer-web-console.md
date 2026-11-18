---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-explorer-web-console
kind: fact
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- explorer
- web-ui
tier: candidate
title: semantica 自带 Web explorer 可视化控制台
updated_at: '2026-11-18T10:56:54.868098Z'
---

semantica-explorer 是项目自带的 Web 控制台，安装方式为 pip install semantica[explorer]，前端是打包好的 React SPA，后端为 FastAPI，提供 graph 等路由，装完即用，无需自写前端。
