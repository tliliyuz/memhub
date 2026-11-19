---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/team-brain-mcp-081223
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/sources/team-brain-mcp-接入指南.md
  type: wiki
supersedes: []
tags:
- mcp
- 只读检索
- 团队大脑
- 双后端
- 接入指南
tier: canonical
title: Team Brain MCP 接入指南
updated_at: '2026-11-18T07:26:22Z'
---

> 把 Wiki / Chat Memory / Skill / 代码图谱统一暴露为 19 个 MCP 只读工具的团队大脑，含双后端设计、各客户端接入、Windows 入口判断坑与验证方法。

# Team Brain MCP 接入指南

## 摘要

本文是 [[Team Brain MCP]] 的接入与设计说明。它是一个 **stdio MCP server**，把团队的三种记忆资产（[[Wiki]] / [[Chat Memory]] / [[Skill]]）与 [[Code Graph]] 统一暴露为 **19 个只读工具**，定位为「**任何 agent 都能读的团队大脑**」。

核心设计结论是**双后端拆分**（见 [[MCP 双后端只读接入]]）：

- Wiki 与代码图谱 → [[Memory Knowledge]]（8424）的 `/v3` 只读端点，**无需密钥**；
- Chat Memory 与 Skill → [[Memory Hub]] 面板 API（8125）`/api/v1` + `sk-mem-` 用户密钥，可离线调用；
- 不经过 [[Memory Proxy]]（8096）的 `memory-bridge` / `skill-bridge`——它们从 `x-conversation-id` 反推身份，脱离活跃会话一律 `40101 session not initialized`。

文中还给出环境变量、四类客户端接入写法、构建方式、两段式验证（后端 health + 面板鉴权 + 12 项自检），以及 5 条踩坑记录。

## 关键结论

| 结论 | 依据 |
|---|---|
| 两个后端，不是一套接口 | `memory-bridge` / `skill-bridge`(8096) 在 MCP 场景不可用（`40101`） |
| 只读，不暴露写操作 | 建 wiki / 删除 / ingest / 分配记忆仍归控制面，避免 agent 误改 |
| 不在模型转发链路上 | 模型链路仍是 `Agent → 8096 Proxy → 3425 Magpie`，检索链与之平行 |
| 无密钥可部分降级 | 缺 `MEMORY_USER_KEY` 时 Chat Memory / Skill 返回配置指引，Wiki 与代码图谱照常可用 |
| Windows 上入口判断是硬坑 | `import.meta.url === file://${process.argv[1]}` 永不相等，进程静默退出 |

## 工具清单（19 个）

| 类别 | 工具 | 后端 |
|---|---|---|
| Wiki（4） | `wiki_search` `wiki_read` `wiki_list` `wiki_graph` | Knowledge 8424 |
| 代码图谱（8） | `code_search` `code_explore` `code_callers` `code_callees` `code_impact` `code_node` `code_status` `code_files` | Knowledge 8424 |
| Chat Memory（5） | `chat_memory_agents` `chat_memory_search` `chat_memory_layer` `chat_memory_list` `chat_memory_stats` | Panel 8125 |
| Skill（2） | `skill_search` `skill_read` | Panel 8125 |

## 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `MEMORY_USER_KEY` | Chat Memory / Skill 必填 | — | `sk-mem-...` 用户密钥；缺失时对应工具返回配置指引 |
| `MEMORY_TEAM_ID` | 建议 | — | 默认团队 id，工具调用可省略 `team_id` |
| `KNOWLEDGE_API_URL` | 否 | `http://127.0.0.1:8424` | Knowledge 服务地址 |
| `MEMORY_PANEL_URL` | 否 | `http://127.0.0.1:8125` | 面板 API 地址 |
| `TDAI_SERVICE_ID` | 否 | `default` | 多实例部署时指定实例 |

`sk-mem-` 用户密钥的来源（本地部署）：`TencentDB-Agent-Memory-local/.admin-key` 文件，或面板 → 账户页。这属于[[凭据分层模型]]中**可以下发到客户端**的那一层。

## 客户端接入

四种写法，`command = node` + `dist/mcp/server.js` 绝对路径 + 同一套 env：

- [[DSH Desktop]]：`~/.dsh/profiles/desktop/cordis.patch.yml` 的 `mcpServers`（需该版本支持 MCP 配置段）；
- [[Codex Desktop]]：`~/.codex/config.toml` 的 `[mcp_servers.team_brain]`，建议 `startup_timeout_sec = 30`；
- Claude Code：`~/.claude/settings.json` 或项目 `.mcp.json`；
- 通用 stdio 客户端：任意支持 MCP stdio 的客户端均可。

## 构建与验证

- 分发产物已含打包好的 `dist/mcp/server.js`（20KB，仅依赖 `@modelcontextprotocol/sdk`）；`npm install --omit=dev` 即可运行。
- 源码重建：`MemoryKnowledge` 目录下 `pnpm install && pnpm build`（tsdown）。
- 两段式验证：
  1. 后端活着：`curl 127.0.0.1:8424/health` 与 `8125/health`；
  2. 面板鉴权有效：`POST /api/v1/chat-memory/mine`，带 `x-tdai-service-id` / `x-tdai-user-key` 与 `team_id`。
- MCP 层自检脚本 `test-client.mjs`：12 项断言（19 工具、双后端调用、无密钥降级），实测 12/12 通过。

## 踩坑记录

1. **Windows 下入口判断失效（已修复）**——见 [[Windows ESM 入口判断失效]]。
2. **`skill_search` 依赖 BM25 分词**——搜「级联」返回 0 条正常，用 `memory`、`wiki` 等真实存在的词才有结果，不是故障。
3. **`chat-memory/mine` 与 `team-assets` 必须带 `team_id`**——漏传 `400 MISSING_TEAM_ID`，MCP 已支持用 `MEMORY_TEAM_ID` 自动补齐。
4. **`chat-memory/layer` 的 `limit` 上限 100**——传 200 直接 400，MCP 层已 clamp。
5. **`block_id` 格式**——必须是 `chat_memory-<team_id>-<agent_id>`，用 `chat_memory_agents` 列出，别手拼。

## 架构位置

```
Agent (任意) ──MCP──> team-brain-mcp (stdio)
                        ├─ /v3 只读 ──> Knowledge 8424 (wiki / code-graph) ─┐
                        └─ /api/v1 + sk-mem ──> Panel 8125 (chat-memory / skill) ─┤
                                                                                ▼
                                                                        Memory Core 8420
```

MCP 是**只读检索层**，不参与模型转发。检索链与 [[级联代理拓扑与分层顺序]] 所描述的模型链**平行、不经过 8096**。

## 对既有认知的更新

- [[Memory Proxy]]：不是所有读取路径的必经点；离线 MCP 场景 bridge 端点不可用。
- [[Code Graph]]：此前「因 DSH 可直接读工作目录而被跳过」的判断需修正——代码图谱已通过 8 个 MCP 工具对外可用。
- [[三类资产模型]]：三类资产新增第三条访问通道「MCP 只读检索」。
- [[静默失效与健康检查盲区]]：新增「Windows 入口判断失效」与「无密钥仅部分降级」两个同类现象。
- [[本地部署拓扑与回环绑定]]：新增一个非监听型组件——stdio MCP 作为客户端子进程回连 127.0.0.1:8424 / 8125。

## 关联页面

[[Team Brain MCP]] · [[MCP 双后端只读接入]] · [[Windows ESM 入口判断失效]] · [[Memory Knowledge]] · [[Memory Hub]] · [[Memory Proxy]] · [[Memory Core]] · [[Code Graph]] · [[Wiki]] · [[Chat Memory]] · [[Skill]] · [[凭据分层模型]] · [[记忆分层 L0–L3]] · [[DSH Desktop]] · [[Codex Desktop]] · [[TencentDB Agent Memory]]

## Citations

- 源文档：`team-brain-mcp-接入指南.md`（含 2026-11-10 实测结论）

## DSH Desktop 接入方式修正（取代前面的 `mcpServers` 写法）

DSH **不使用 `mcpServers` 块，也没有独立的 mcp 配置文件**。它是 Cordis 插件框架，MCP 通过 `@deepseek-ai/dsh-mcp-client` 插件接入，**一个插件实例对应一个 MCP server**。详见 [[DSH Cordis 插件式 MCP 接入]]。

- 权威出处：`D:/dsh/DSH Desktop/resources/app/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js`；官方模板 `.../dsh-agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml`
- `transport` 二选一：`stdio`（`serverName` + `command` 必填）或 `streamable-http`（`serverName` + `url` 必填）
- `serverName` 须匹配 `^[A-Za-z0-9_-]{1,32}$`，同一 Agent 内不可重复
- 工具名映射为 `mcp__<serverName>__<toolName>`，如 `mcp__team_brain__wiki_search`
- 三个必踩的坑：`command` 必须用**绝对路径**（GUI 进程 PATH 与 shell 不同）；server.js 必须**自包含打包**（`--packages=external` 会 `ERR_MODULE_NOT_FOUND`）；profile 目录没有 `node_modules` 也能解析插件（走 app 目录的 node_modules，无需 `dsh plugin install`）
- 验证：重启 DSH 后工具列表中应出现 19 个 `mcp__team_brain__*` 工具

## 补充数据

- 全量自包含打包后的 `dist/mcp/server.js` 约 610KB（对照：最小依赖版 20KB）。
- 启动自检应打印 `MCP server connected via stdio`。

## 待确认

MCP 的 Cordis 插件 entry 写入 `~/.dsh/profiles/desktop/cordis.patch.yml`，而 [[DSH 双 Provider 体系与设置覆盖层]] 记录 `~/.dsh/settings.yaml` 优先级更高且可能在重启时被重写——**插件 entry 是否会被 settings.yaml 覆盖/重写冲掉，尚待验证**。
