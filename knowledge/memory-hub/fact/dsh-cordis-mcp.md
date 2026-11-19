---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/dsh-cordis-mcp
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/dsh-cordis-插件式-mcp-接入.md
  type: wiki
supersedes: []
tags:
- dsh
- cordis
- mcp
- 插件
- 接入模型
tier: canonical
title: DSH Cordis 插件式 MCP 接入
updated_at: '2026-11-18T07:26:22Z'
---

> DSH 没有 mcpServers 配置块，MCP 只能通过 @deepseek-ai/dsh-mcp-client Cordis 插件 entry 写入 cordis.patch.yml，一个插件实例对应一个 server，工具名映射为 mcp__<serverName>__<toolName>。

# DSH Cordis 插件式 MCP 接入

## 定义

[[DSH Desktop]] 是 Cordis 插件框架，**没有 `mcpServers` 配置块，也没有独立的 mcp 配置文件**。MCP server 的接入方式是：在 `~/.dsh/profiles/desktop/cordis.patch.yml` 的顶层 entry 列表里追加一个 entry，`name` 为 `@deepseek-ai/dsh-mcp-client`，`config` 描述该 server 的 transport 与参数。

**一个插件实例只连一个 MCP server**；接多个 server 就在 `cordis.patch.yml` 里写多个 entry。

## 意义

这是与标准 MCP 客户端（[[Codex Desktop]] 的 `[mcp_servers.*]`、[[Claude Code]] 的 `mcpServers`）**完全不同的一套接入模型**。误按标准写法在 DSH 里写 `mcpServers:` 会静默不生效——这是 [[Team Brain MCP]] 接入时最容易走错的一步。

## 配置 schema（来自插件源码）

`transport` 二选一：

| transport | 必填字段 | 可选字段 |
|---|---|---|
| `stdio` | `serverName` `command` | `args[]` `env{}` `cwd` `toolCallTimeoutMs` `failOnStartupError` `maxInstructionBytes` `reconnect` |
| `streamable-http` | `serverName` `url` | `headers{}` `toolCallTimeoutMs` `failOnStartupError` |

约束：

- `serverName` 必须匹配 `^[A-Za-z0-9_-]{1,32}$`，且同一 Agent 内不可重复
- 注册后的工具名格式为 **`mcp__<serverName>__<toolName>`**，例如 `mcp__team_brain__wiki_search`
- 与 [[DSH 双 Provider 体系与设置覆盖层]] 同为 `cordis.patch.yml` 的写入方

## 相关实体与来源

- [[DSH Desktop]] —— 宿主应用
- [[Team Brain MCP]] —— 被接入的 MCP server
- 插件实现：`D:/dsh/DSH Desktop/resources/app/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js`
- 官方模板：`.../dsh-agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml`

官方模板原文：

```yaml
- insert:
    - id: demo-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: demo
        transport: streamable-http
        url: http://127.0.0.1:3000/mcp
        failOnStartupError: true
```

## Examples

本项目接入 Team Brain MCP 的实际写法（追加到 `~/.dsh/profiles/desktop/cordis.patch.yml` 顶层 entry 列表末尾）：

```yaml
- id: team-brain-mcp
  name: "@deepseek-ai/dsh-mcp-client"
  config:
    serverName: team_brain
    transport: stdio
    command: "D:/develop/nodejs/node.exe"        # 用绝对路径，避免 PATH 差异
    args:
      - "D:/workplace/TencentDB-Agent-Memory-local/team-brain-mcp/dist/mcp/server.js"
    env:
      MEMORY_USER_KEY: "sk-mem-xxxx"
      MEMORY_TEAM_ID: "team-xxxx"
      KNOWLEDGE_API_URL: "http://127.0.0.1:8424"
      MEMORY_PANEL_URL: "http://127.0.0.1:8125"
      LOG_LEVEL: "warn"
    toolCallTimeoutMs: 60000
    failOnStartupError: false
```

`streamable-http` 形态只需换成 `url` + 可选 `headers{}`，适合把 MCP server 作为常驻服务部署时使用。

## 三个必踩的坑

1. **`command` 必须用绝对路径**。DSH 由 GUI 启动，其进程 PATH 未必包含 shell 里的 `node`，写 `node` 可能 spawn 失败。详见 [[stdio MCP 分发与启动约束]]。
2. **server.js 必须自包含打包**。用 `--packages=external` 打包时，profile/部署目录没有 `node_modules` 就报 `ERR_MODULE_NOT_FOUND`；正确做法是全量打包（含 SDK），单文件约 610KB。
3. **profile 没有 `node_modules` 也能解析插件**。`dsh-client-ui-chat` 等插件同样只在 app 目录存在却能加载，说明解析走 app 的 `node_modules`，`dsh-mcp-client` 同理可用，**无需 `dsh plugin install`**。

## 验证

重启 DSH 后，模型可用工具列表中应出现 19 个 `mcp__team_brain__*` 工具；也可让 agent 直接调用 `mcp__team_brain__wiki_search` 验证。这只是 MCP 层的最后一层，后端健康与鉴权需按 [[静默失效与健康检查盲区]] 的三层验证先排。

## 待确认问题

`~/.dsh/settings.yaml` 优先级高于 `cordis.patch.yml` 且可能在重启时被重写（见 [[DSH 双 Provider 体系与设置覆盖层]]）。**MCP 的插件 entry 是否也会被 settings.yaml 覆盖或重写冲掉，尚待验证。**

## Citations

- `team-brain-mcp-接入指南.md` 第 8 节（2026-11-10 查证）
