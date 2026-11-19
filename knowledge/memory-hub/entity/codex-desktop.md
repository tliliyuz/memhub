---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: memory-hub/entity/codex-desktop
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/codex-desktop.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 客户端
- codex
- mcp
- config.toml
tier: canonical
title: Codex Desktop
updated_at: '2026-11-18T07:26:22Z'
---

> 保留 OpenAI 官方供应商、直连上游不经过 Memory Proxy 的客户端；历史记忆写入依赖仓库自带的会话导入工具，2026-11-10 起可在 ~/.codex/config.toml 的 [mcp_servers.team_brain] 中配置 Team Brain MCP，以只读方式实时读取团队资产。

# Codex Desktop

## 定义

Codex Desktop 是接入 [[TencentDB Agent Memory]] 的另一条客户端路径。用户要求保留 OpenAI 官方供应商，因此请求直连上游、**不经过** [[Memory Proxy]]，无法在会话内自动获得记忆注入；历史记忆只能通过 [[Codex 会话导入工具]] 把选定的历史会话关联到 `applesay → sdp-tag-doc`，交由 Memory 提炼。

- Kind：`external_system`（客户端）。新页 frontmatter 曾记为 `kind: other`；本页按客户端实体归类保留 `external_system`，并记录该分类差异。
- 配置目录：`~/.codex/`
- 记忆路径为「事后导入」，而非实时注入。
- 模型调用不经过 Proxy：不在 [[级联代理拓扑与分层顺序]] 的链路上。
- 2026-11-10 起，可通过 [[Team Brain MCP]] 以只读方式实时读取团队资产；写入/沉淀仍为导入式。

## 关键属性

| 项 | 值 |
| --- | --- |
| 供应商 | OpenAI 官方（用户要求保留） |
| 是否经过 Proxy | 否（直连）；不在 [[级联代理拓扑与分层顺序]] 的链路上 |
| 记忆写入方式 | [[Codex 会话导入工具]] 导入历史会话，关联 `applesay → sdp-tag-doc` 后由 Memory 提炼 |
| 记忆读取方式 | 默认无实时注入；2026-11-10 起可经 [[Team Brain MCP]] 只读实时读取团队资产 |
| MCP 配置位置 | `~/.codex/config.toml` 的 `[mcp_servers.team_brain]` 段 |
| 配置目录 | `~/.codex/` |
| 已导出资产 | 108 个 SDP Tag 相关会话 Markdown，索引 `D:\workplace\codex-sdp-tag-sessions\README.md` |

- 记忆写入仍为「事后导入」，不是实时注入或自动沉淀。
- MCP 检索是 Codex 获取团队资产的主要方式；但它提供的仍是只读能力。

## MCP 接入（2026-11-10 起）

在 `~/.codex/config.toml` 中追加：

```toml
[mcp_servers.team_brain]
command = "node"
args = ["D:/workplace/TencentDB-Agent-Memory-local/team-brain-mcp/dist/mcp/server.js"]
startup_timeout_sec = 30

[mcp_servers.team_brain.env]
MEMORY_USER_KEY = "sk-mem-xxxx"
MEMORY_TEAM_ID = "team-xxxx"
```

要点：

- `startup_timeout_sec = 30` 用于容纳 Node 冷启动与首次后端连接；**该超时设置是必需的**，因为 Node 冷启动加首次连接后端可能超过默认超时。
- 接入后 Codex 可**实时读取**团队资产（[[Team Brain MCP]] 的 19 个只读工具），补上了它缺少的「读记忆」能力——但**写/沉淀**仍是导入式的。
- 与 [[DSH Desktop]] 的 Cordis 插件写法完全不同，Codex 使用的是标准 `[mcp_servers.*]` 段；参见 [[DSH Cordis 插件式 MCP 接入]] 的对照。
- `command = "node"` 在 Codex 中可用，但仍建议核对 PATH；参见 [[stdio MCP 分发与启动约束]]。
- 历史会话归档走 [[Codex 会话导入工具]] → [[Memory Agent]]。

## 已验证 / 未验证（显式标注）

- **未验证**：Codex 桌面端通过 Proxy 归档。
- **未配置**：自动同步。
- 仅验证过：早前建立的 `memory` profile 的 CLI 链路。
- 说明：Markdown 导出与导入 [[Chat Memory]] 是两条独立操作。

> **记录差异说明**：旧页称 Codex「只能通过仓库自带的会话导入工具把历史会话导入 Memory」；新页补充 2026-11-10 起可通过 [[Team Brain MCP]] 只读实时读取团队资产。二者在「读取路径」上不一致，按较新记录更新为：**读取可经 MCP，写入仍仅导入**。旧页关于「不经过 Proxy、无自动归档」的判断仍然成立。

## 关系

- 与 [[Codex 会话导入工具]]：唯一经验证的历史记忆写入入口；导入时关联 `applesay → sdp-tag-doc`，见 [[项目记忆归属与 Agent 分配]]。
- 与 [[Team Brain MCP]]：2026-11-10 起提供 19 个只读工具，补足 Codex 的实时读取能力，是获取团队资产的主要方式。
- 与 [[Chat Memory]]：导入历史 vs 自动提炼是两条独立更新路径。
- 与 [[Memory Agent]]：导入时关联 `applesay → sdp-tag-doc` → [[项目记忆归属与 Agent 分配]]。
- 与 [[DSH Desktop]]：对比——DSH 走内置提供商 + Proxy，可自动归档/实时注入；Codex 不走 Proxy，写入依赖导入、读取可经 MCP。MCP 配置上，DSH 使用 Cordis 插件式写法，Codex 使用标准 `[mcp_servers.*]`，参见 [[DSH Cordis 插件式 MCP 接入]]。
- 与 [[Memory Proxy]]：Codex 直连上游、不经过 Proxy，因此不享有自动记忆注入；MCP 检索是它获取团队资产的主要方式。
- 与 [[级联代理拓扑与分层顺序]]：Codex 的模型调用不在该链路上。
- 与 [[stdio MCP 分发与启动约束]]：`command = "node"` 在 Codex 中可用，但仍建议核对 PATH。

## Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §3
- `team-brain-mcp-接入指南.md` 第 3 节
