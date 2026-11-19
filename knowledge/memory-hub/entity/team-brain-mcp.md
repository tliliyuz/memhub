---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/team-brain-mcp
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/team-brain-mcp.md
  type: wiki
supersedes: []
tags:
- mcp
- service
- 只读检索
- 团队大脑
- stdio
tier: canonical
title: Team Brain MCP
updated_at: '2026-11-18T07:26:22Z'
---

> 以 stdio 方式运行的 MCP server，把 Wiki / Chat Memory / Skill / 代码图谱聚合为 19 个只读工具，按双后端路由，是团队资产的统一只读入口。

# Team Brain MCP

## Kind

`service`（stdio 子进程型服务，无监听端口）

## Definition

Team Brain MCP（仓库目录 `team-brain-mcp`，入口 `node dist/mcp/server.js`）是一个 **stdio MCP server**，把团队的三种记忆资产（[[Wiki]] / [[Chat Memory]] / [[Skill]]）与 [[Code Graph]] 统一暴露为 **19 个只读工具**，定位为「**任何 agent 都能读的团队大脑**」。它本身不存储数据、不转发模型请求，只做**只读检索层**。

它让任何支持 MCP 的 agent 无需理解平台内部接口，就能检索团队的记忆资产与代码结构，是团队资产的**统一只读出口**。

## Key Attributes

### 运行方式

- 由客户端以 `command = node` + `args = [<server.js 绝对路径>]` 拉起，走 MCP stdio。
- 启动成功打印 `MCP server connected via stdio`。
- 作为 stdio 子进程它**不监听任何端口**，只回连 `127.0.0.1:8424` / `127.0.0.1:8125`，见 [[本地部署拓扑与回环绑定]]。

### 分发产物

- 已含打包好的 `dist/mcp/server.js`；源码在 `TencentDB-Agent-Memory/MemoryKnowledge`，`pnpm build`（tsdown）重建。
- 旧页记载：`dist/mcp/server.js` 约 **20KB**，仅依赖 `@modelcontextprotocol/sdk`，`npm install --omit=dev` 即可运行。
- 新页记载：**必须全量自包含打包**（含 SDK），单文件约 **610KB**；用 `--packages=external` 会在无 `node_modules` 的部署目录报 `ERR_MODULE_NOT_FOUND`。
- **两处记载不一致**：体积与打包方式不同，可能对应不同版本或构建配置；部署时以实际产物与启动自检为准。
- 启动自检：`node dist/mcp/server.js` 应打印 `MCP server connected via stdio`。
- 分发与启动约束详见 [[stdio MCP 分发与启动约束]]。

### 双后端路由

按「是否需要身份」拆成两个后端，即 [[MCP 双后端只读接入]]：

- [[Memory Knowledge]]（8424）—— `/v3` 只读端点，**免密钥**，承载 [[Wiki]] 与 [[Code Graph]]；可用性受 `knowledge.enabled` 开关控制。
- [[Memory Hub]]（8125）—— `/api/v1` + `sk-mem-` 用户密钥，承载 [[Chat Memory]] 与 [[Skill]]，可离线调用。
- 两个后端最终都落到 [[Memory Core]]（8420）。

### 只读边界

写操作（建 wiki / 删除 / ingest / 分配记忆）**不暴露**给 MCP，仍由控制面负责，避免 agent 误改。

### 不在模型链路上

模型调用仍是 `Agent → 8096 Proxy → 3425 Magpie`，与检索链平行；MCP 是**只读检索层**，不参与转发。见 [[级联代理拓扑与分层顺序]]。

### 工具清单（19 个只读工具）

| 类别 | 数量 | 工具 | 后端 |
|---|---|---|---|
| Wiki | 4 | `wiki_search` `wiki_read` `wiki_list` `wiki_graph` | [[Memory Knowledge]] 8424 |
| 代码图谱 | 8 | `code_search` `code_explore` `code_callers` `code_callees` `code_impact` `code_node` `code_status` `code_files` | [[Memory Knowledge]] 8424 |
| Chat Memory | 5 | `chat_memory_agents` `chat_memory_search` `chat_memory_layer` `chat_memory_list` `chat_memory_stats` | [[Memory Hub]] 8125 |
| Skill | 2 | `skill_search` `skill_read` | [[Memory Hub]] 8125 |

### 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `MEMORY_USER_KEY` | Chat Memory / Skill 必填 | — | `sk-mem-...` 用户密钥；缺失时这两类工具返回配置指引，Wiki / 代码图谱仍可用（无密钥降级） |
| `MEMORY_TEAM_ID` | 建议 | — | 默认团队 id，调用可省略 `team_id` |
| `KNOWLEDGE_API_URL` | 否 | `http://127.0.0.1:8424` | Memory Knowledge 地址 |
| `MEMORY_PANEL_URL` | 否 | `http://127.0.0.1:8125` | Memory Hub 面板 API 地址 |
| `TDAI_SERVICE_ID` | 否 | `default` | 多实例部署时指定实例 |

`sk-mem-` 用户密钥来源：`TencentDB-Agent-Memory-local/.admin-key`，或面板 → 账户页。属于 [[凭据分层模型]] 中可下发到客户端的那一层。

### 客户端接入矩阵

| 客户端 | 配置位置 | 关键点 |
|---|---|---|
| [[DSH Desktop]] | `~/.dsh/profiles/desktop/cordis.patch.yml` | **接入方式两页记载不一致**：旧页称走 `mcpServers` 配置段且需该版本支持 MCP 配置；新页称该文件**无 `mcpServers` 块**，通过 `@deepseek-ai/dsh-mcp-client` Cordis 插件接入，见 [[DSH Cordis 插件式 MCP 接入]]。以实际 DSH 版本为准 |
| [[Codex Desktop]] | `~/.codex/config.toml` 的 `[mcp_servers.team_brain]` | 建议 `startup_timeout_sec = 30` |
| [[Claude Code]] | `~/.claude/settings.json` 或项目 `.mcp.json` | 标准 MCP 客户端写法，`mcpServers` 同构 JSON |
| 通用 stdio 客户端 | — | `command = node` + `args = [server.js 绝对路径]` + 同套 env |

## 验证

三层验证：后端健康（`/health`）→ 面板鉴权（`chat-memory/mine` 带 key + `team_id`）→ MCP 层自检。

1. 后端活着：`curl 127.0.0.1:8424/health`、`curl 127.0.0.1:8125/health`。
2. 面板鉴权有效：`POST /api/v1/chat-memory/mine`，带 `x-tdai-service-id` / `x-tdai-user-key` 与 `team_id`。
3. MCP 层自检：仓库内 `test-client.mjs`，12 项断言（19 工具存在性、双后端真实调用、无密钥降级），实测 12/12 通过。该脚本是属性而非独立实体，不单独立页。

## 已知坑位

| 现象 | 结论 |
|---|---|
| 启动即静默退出，客户端见 `Connection closed` | [[Windows ESM 入口判断失效]]：已修复，改用 `pathToFileURL(process.argv[1]).href` 比较 |
| `skill_search` 搜某词返回 0 条 | 走 BM25 分词，正常行为，**不是故障**，见 [[静默失效与健康检查盲区]] |
| `400 MISSING_TEAM_ID` | `chat-memory/mine` 与 `team-assets` 必须带 `team_id`；漏传可用 `MEMORY_TEAM_ID` 自动补齐 |
| `chat-memory/layer` 传 200 → 400 | `limit` 上限 100，MCP 层已 clamp，见 [[记忆分层 L0–L3]] |
| `block_id` 校验失败 | 必须是 `chat_memory-<team_id>-<agent_id>`，应由 `chat_memory_agents` 列出而非手拼，见 [[项目记忆归属与 Agent 分配]] |
| 缺 `MEMORY_USER_KEY` | Chat Memory / Skill 返回配置指引，Wiki / 代码图谱仍可用（部分降级），见 [[凭据分层模型]] |

## Relationships

- 上游后端：[[Memory Knowledge]]（`/v3` 只读、**无需密钥**）、[[Memory Hub]]（面板 `/api/v1` + `sk-mem-` 用户密钥）。
- 两个后端最终共享底层存储 [[Memory Core]]（8420）。
- 绕开 [[Memory Proxy]] 的 `memory-bridge` / `skill-bridge`（8096）：它们按 `x-conversation-id` 反推身份，脱离活跃 DSH 会话时离线场景返回 `40101`，因此**不被 MCP 使用**。
- 被 [[DSH Desktop]]、[[Codex Desktop]]、[[Claude Code]] 等客户端作为子进程拉起。
- 是 [[TencentDB Agent Memory]] 平台面向 agent 的统一读取出口。
- 支撑 [[三类资产模型]] 的第三条访问通道「MCP 只读检索」，并对外提供 [[Code Graph]] 的 8 个查询工具。
- 概念承载：[[MCP 双后端只读接入]]；分发与启动约束见 [[stdio MCP 分发与启动约束]]；DSH 插件式接入见 [[DSH Cordis 插件式 MCP 接入]]；本地回环绑定见 [[本地部署拓扑与回环绑定]]。
- 风险归类见 [[静默失效与健康检查盲区]]；与 [[级联代理拓扑与分层顺序]] 平行不相交。

## Citations

- `team-brain-mcp-接入指南.md` 第 1、2、4、5、6、7、9 节
