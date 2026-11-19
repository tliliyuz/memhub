---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/memory-core
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/memory-core.md
  type: wiki
supersedes: []
tags:
- 服务
- 存储
- 核心服务
- sqlite
- 持久化
- '8420'
- 核心
tier: canonical
title: Memory Core
updated_at: '2026-11-18T07:26:22Z'
---

> 监听 8420 的核心服务，默认使用 SQLite，数据持久化在 Docker 卷 tdai-memory-core-data；是记忆平台的数据与逻辑底座，也是 MCP 两个后端的共同底层。

# 定义

`memory-core`（容器名 `tdai-memory-core`）是 [[TencentDB Agent Memory]] 的核心服务，承载记忆数据的存储与核心处理逻辑。监听 **8420**（绑定 127.0.0.1）。默认使用 SQLite，数据持久化在 Docker 卷 `tdai-memory-core-data`。它是整个记忆平台的数据与逻辑底座。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 容器 | `tdai-memory-core` |
| 端口 | 8420（仅 127.0.0.1） |
| 存储 | 默认 SQLite |
| 持久化卷 | Docker 卷 `tdai-memory-core-data` |
| 平台定位 | 记忆平台的数据与逻辑底座；[[Team Brain MCP]] 两个后端的共同底层 |

# 关系

- 组成：[[TencentDB Agent Memory]] 的四个服务之一（见 [[本地部署拓扑与回环绑定]]）
- 与 [[Memory Hub]]（8125）、[[Memory Knowledge]]（8424）、[[Memory Proxy]]（8096）共同构成平台四服务；Wiki 与知识索引由 Hub 管理，Core 承担核心数据面。
- 与 [[Chat Memory]]：会话记忆（L0–L3）的持久化落点，见 [[记忆分层 L0–L3]]；Core 承载 [[记忆分层 L0–L3]] 各层数据。
- 端口/绑定总表见 [[本地部署拓扑与回环绑定]]。
- [[Memory Knowledge]]（8424）与 [[Memory Hub]]（8125）都向下落到它——即 [[Team Brain MCP]] 的**两个后端最终汇聚于同一个核心**。
- 因此 MCP 架构图上两个箭头最终汇到一处（见 [[Team Brain MCP]] 的架构位置小节）。
- [[Memory Proxy]]（8096）的记忆注入与 L0 落库同样写入它。

# 待补充

- Core 与 Knowledge 之间的调用边界，源文档未展开。

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §2
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` 第 7 节
