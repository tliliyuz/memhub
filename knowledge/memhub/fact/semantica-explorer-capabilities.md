---
confidence: 0.9
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/fact/semantica-explorer-capabilities
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
- tooling
tier: candidate
title: Semantica Explorer 的页面与 API 能力全景
updated_at: '2026-11-18T10:56:54.868098Z'
---

Semantica Explorer 开箱即用的能力：页面组件即功能页——GraphWorkspace（图谱浏览、节点详情、邻居遍历、两点找路径）、KGOverviewTab（总览统计）、DecisionWorkspace（决策记录与因果链追踪 causal-distance/precedents）、EntityResolutionTab 与 DiffMergeWorkspace（实体去重与冲突合并，自带人工确认界面）、MemoryWorkspace（记忆/事实管理）、MarkdownContentViewer（直接渲染 markdown）。后端 14 组路由：graph、analytics、decisions、temporal（时间快照）、enrich（在线抽取/链接/去重）、export_import、markdown（挂载 markdown 目录）、sparql、provenance（溯源查询）、annotations、ontology、vocabulary。启动方式 `semantica-explorer`，浏览器直开；设 SEMANTICA_API_KEY 环境变量即启用认证，不设则本机匿名（LAN 部署应设）。数据源支持挂 kg.json 图文件或 markdown 目录模式。
