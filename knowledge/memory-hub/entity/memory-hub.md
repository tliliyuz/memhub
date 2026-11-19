---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/memory-hub
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/memory-hub.md
  type: wiki
supersedes: []
tags:
- 服务
- '8125'
- 面板
- 管理服务
- api
- 鉴权
- wiki-ingest
- mcp 后端
tier: canonical
title: Memory Hub
updated_at: '2026-11-18T07:26:22Z'
---

> 面向人的面板服务，监听 8125，容器 tdai-memory-hub（同容器还映射 8424 给 Knowledge），提供 /api/v1 面板 API 与运维查询能力，负责 Wiki 与知识索引的分配、就绪校验与 Ingest 触发；2026-11-10 起同时充当 MCP 的 Chat Memory/Skill 只读后端（5 个 chat_memory_* + 2 个 skill_* 工具），并通过账户页提供本地 sk-mem- 用户密钥来源之一。

# Memory Hub

## 定义

`memory-hub`（Memory Hub）是 [[TencentDB Agent Memory]] 中**面向人的 Web 面板服务**，监听 **8125**，容器 `tdai-memory-hub`（同容器还映射 8424 给 [[Memory Knowledge]]）。它承担管理职责：[[Wiki]] 的分配、就绪状态校验与 Ingest 触发，以及知识索引的维护；同时提供 `/api/v1` 面板 API 与运维查询能力（记忆计数、团队资产总览、Wiki 列表）。2026-11-10 起，它同时充当 [[Team Brain MCP]] 的 Chat Memory（5 个工具）与 Skill（2 个工具）的**只读后端**（共 7 个工具），是 [[MCP 双后端只读接入]] 中「需要身份」那一侧的后端。

## 关键属性

| 属性 | 值 |
| --- | --- |
| 容器 | `tdai-memory-hub`（一个容器同时映射 8125 与 8424） |
| 端口 | 8125（仅 127.0.0.1）；同容器另映射 8424 给 [[Memory Knowledge]] |
| 面板地址 | http://127.0.0.1:8125/ |
| API 前缀 | **`/api/v1/`**（不是 `/api/`） |
| 健康检查 | `GET /health` |
| 分页上限 | `limit` 硬上限 **100** |
| 必需请求头 | `x-tdai-service-id`（默认 `default`）、`x-tdai-user-key`（`sk-mem-` 用户密钥）、`content-type: application/json` |
| 管理对象 | [[Wiki]]、知识索引 |
| 密钥来源 | 账户页是本地获取 `sk-mem-` 用户密钥的两个来源之一（另一个是 `.admin-key` 文件），见 [[凭据分层模型]] |
| MCP 指向 | `MEMORY_PANEL_URL`（默认 `http://127.0.0.1:8125`） |

## 常用面板 API

| 端点 | 用途 | 关键入参 |
| --- | --- | --- |
| `POST /api/v1/chat-memory/layer` | 查某 Agent 某层记忆计数与条目 | `block_id=chat_memory-<team_id>-<agent_id>`、`layer`（L0–L3）、`limit` |
| `POST /api/v1/chat-memory/mine` | Chat Memory 查询（MCP 工具后端） | 必须带 `team_id` |
| `POST /api/v1/chat-memory/team-assets` | 团队资产查询（MCP 工具后端） | 必须带 `team_id` |
| `POST /api/v1/agent-overview/bootstrap` | 团队资产总览 | `team_id` |
| `POST /api/v1/knowledge/wiki/list` | Wiki 列表 | `team_id` |
| skill 相关端点 | Skill 查询（MCP 工具后端） | — |

这些端点在 [[级联代理拓扑与分层顺序]] 的第五步验证中被用来确认「记忆是否真的在涨」：对话几轮后 L0 / L1 的 `total` 应增长。

## MCP 接入约束（2026-11-10）

- 面板 API 可**脱离会话离线调用**，这是它取代 [[Memory Proxy]] 的 `memory-bridge` / `skill-bridge` 成为 MCP 后端的原因（后者 `40101`）。也正因只需用户密钥、不需要会话上下文，它是 MCP 的**唯一可选后端**——[[Memory Proxy]] 的 bridge 端点因会话耦合被排除。
- 承载 5 个 `chat_memory_*` + 2 个 `skill_*` 工具（共 7 个），服务 [[Chat Memory]] 与 [[Skill]]。
- MCP 侧通过 `MEMORY_PANEL_URL`（默认 `http://127.0.0.1:8125`）指向它。
- `chat-memory/mine` 与 `chat-memory/team-assets` **必须带 `team_id`**，否则 `400 MISSING_TEAM_ID`。
- `chat-memory/layer` 的 `limit` **上限 100**，传 200 直接 400（MCP 层已 clamp）。
- Chat Memory 的 `block_id` 必须是 `chat_memory-<team_id>-<agent_id>`，应由 `chat_memory_agents` 工具先列出。
- `sk-mem-` 用户密钥可下发到客户端（MCP env），属于 [[凭据分层模型]] 中可下发的那一层；账户页是本地获取该密钥的来源之一。

## Examples

面板鉴权自检（三层验证的第 2 层）：

```bash
curl -X POST http://127.0.0.1:8125/api/v1/chat-memory/mine \
  -H 'content-type: application/json' \
  -H 'x-tdai-service-id: default' \
  -H 'x-tdai-user-key: sk-mem-xxxx' \
  -d '{"team_id":"team-xxxx"}'
```

见 [[静默失效与健康检查盲区]]。

## 关系

- 组成：[[TencentDB Agent Memory]] 的四个服务之一（见 [[本地部署拓扑与回环绑定]]）。
- 同容器承载 [[Memory Knowledge]]（8424）。
- 与 [[Memory Core]]（8420）、[[Memory Proxy]]（8096）共同构成平台四服务，见 [[本地部署拓扑与回环绑定]]。
- 底层存储依赖 [[Memory Core]]（8420）。
- 是 [[MCP 双后端只读接入]] 中「需要身份」那一侧的后端，承载 5 个 `chat_memory_*` + 2 个 `skill_*` 工具（共 7 个），服务 [[Chat Memory]] 与 [[Skill]]；即被 [[Team Brain MCP]] 作为 **Chat Memory（5 个工具）与 Skill（2 个工具）的只读后端**。在 MCP 接入中取代 [[Memory Proxy]] 的 `memory-bridge` / `skill-bridge`（后者 `40101`，且因会话耦合被排除）。
- 与 [[Wiki]]：Wiki 必须先分配、进入就绪状态后才能被 Agent 使用；上传源材料触发 Ingest。
- 与 [[Wiki Ingest 加工管线]]：Ingest 的管理入口与状态展示。
- 与 [[SDP Tag 项目]]：`sdp-tag` Wiki 的加工快照（170 页 / `processing`）来自该面板与数据库记录。
- 记忆分层语义见 [[记忆分层 L0–L3]]。

## 待补充

- 知识索引的具体数据模型与调度机制（文末信息单薄）。

## Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §2、§5.5、§6
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §1、§2、§5、§6
