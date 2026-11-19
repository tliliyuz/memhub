---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: memory-hub/entity/claude-code
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/claude-code.md
  type: wiki
supersedes: []
tags:
- 客户端
- claude-code
- mcp
tier: canonical
title: Claude Code
updated_at: '2026-11-18T07:26:22Z'
---

> 标准 MCP 客户端，在 ~/.claude/settings.json 或项目 .mcp.json 的 mcpServers 段接入 Team Brain MCP，与 Codex 的 TOML 写法、DSH 的 Cordis 插件写法形成三方对照。

# Claude Code

## 定义

第三方 agent 客户端，支持标准 MCP 配置。2026-11-10 起作为 [[Team Brain MCP]] 的第三类接入客户端被验证，与 [[Codex Desktop]]、[[DSH Desktop]] 构成客户端接入矩阵。

## MCP 接入写法

写入 `~/.claude/settings.json`（全局）或项目级 `.mcp.json`：

```json
{
  "mcpServers": {
    "team-brain": {
      "command": "node",
      "args": ["D:/workplace/TencentDB-Agent-Memory-local/team-brain-mcp/dist/mcp/server.js"],
      "env": {
        "MEMORY_USER_KEY": "sk-mem-xxxx",
        "MEMORY_TEAM_ID": "team-xxxx"
      }
    }
  }
}
```

- 采用**标准 `mcpServers` 写法**，工具名不带前缀改写（原样使用 `wiki_search` 等）
- 与 [[DSH Desktop]] 的 Cordis 插件 entry **不通用**——同一份配置不能复制到 `cordis.patch.yml`
- project 级 `.mcp.json` 便于把团队大脑配置随仓库分发

## 关系

- 只读消费 [[Team Brain MCP]] 的 19 个工具
- `env` 中携带 `sk-mem-` 用户密钥，属 [[凭据分层模型]] 的客户端落点

## Citations

- `team-brain-mcp-接入指南.md` 第 3 节
