---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/wiki
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/wiki.md
  type: wiki
supersedes: []
tags:
- 资产
- 知识库
- wiki
- mcp
- 只读检索
tier: canonical
title: Wiki
updated_at: '2026-11-18T07:26:22Z'
---

> 文档型知识资产，需先分配、就绪后才能使用；上传选定源材料触发 Ingest；会话记忆不会自动写入；2026-11-10 起可通过 MCP 的 wiki_search / wiki_read / wiki_list / wiki_graph 只读检索。

# Wiki

## 定义

Wiki 是由**源材料**加工而成的**文档型知识资产**，由 [[Memory Hub]] 管理分配与就绪状态。使用前置条件明确：需先把 Wiki **分配**给项目/Agent，且状态**就绪**后才能检索；内容更新靠上传选定的源材料触发 [[Wiki Ingest 加工管线]]。会话记忆**不会自动写入** Wiki——这是它与 [[Chat Memory]] 的核心区别。

## 意义

Wiki 承载「正式、结构性」的知识（架构设计、RFC、规范），与承载「隐性经验」的 Chat Memory 互补，见 [[三类资产模型]]、[[记忆沉淀策略]]。

## 使用方式

- Agent 搜索**已分配**的 Wiki，再读取命中页面。
- 面板要求 Wiki **就绪后**才能分配使用。

## 更新方式

- 上传**选定的源材料**后触发 [[Wiki Ingest 加工管线]]。
- **会话记忆不会自动写进 Wiki**（与 [[Chat Memory]] 的关键区别）。

## 对外读取接口（2026-11-10 起）

[[Team Brain MCP]] 暴露 4 个只读工具：

| 工具 | 用途 |
|---|---|
| `wiki_search` | 语义检索页面 |
| `wiki_read` | 读取页面正文 |
| `wiki_list` | 列出可用 Wiki / 页面 |
| `wiki_graph` | 读取页面间关系图 |

后端是 [[Memory Knowledge]]（8424）的 `/v3` 只读端点，**无需密钥**，因此即使 `MEMORY_USER_KEY` 缺失，这 4 个工具仍可用（见 [[MCP 双后端只读接入]]）。可用性受 `knowledge.enabled` 开关控制。

在 [[DSH Desktop]] 中调用时工具名为 `mcp__team_brain__wiki_search` 等，见 [[DSH Cordis 插件式 MCP 接入]]。

## 相关实体

[[Memory Hub]]、[[Memory Knowledge]]、[[Wiki Ingest 加工管线]]、[[SDP Tag 项目]]（`sdp-tag` Wiki）、[[三类资产模型]]、[[Chat Memory]]、[[记忆沉淀策略]]、[[Team Brain MCP]]、[[MCP 双后端只读接入]]、[[DSH Desktop]]、[[DSH Cordis 插件式 MCP 接入]]

# Citations

- `tencentdb-agent-memory-session.md`
- `team-brain-mcp-接入指南.md` 第 1 节
