---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: memory-hub/entity/dsh-desktop
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/dsh-desktop.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 客户端
- dsh
- coding-agent
- mcp
tier: canonical
title: DSH Desktop
updated_at: '2026-11-18T07:26:22Z'
---

> 通过内置 DeepSeek 提供商接入 Memory Proxy 的客户端，会话可绑定 Memory Agent 并自动归档，是当前经验证可用的归档路径；2026-11-10 追加 Magpie 模型后可选模型由 2 个增至 66 个，并支持以 mcpServers 配置接入 Team Brain MCP。

# 定义

DSH Desktop 是团队使用的桌面 AI 客户端，也是接入 [[TencentDB Agent Memory]] 的客户端。使用内置 DeepSeek 提供商时，请求经 [[Memory Proxy]] 转发，会话可绑定 [[Memory Agent]] 并在满足条件时自动提炼为 [[Chat Memory]]，是当前经验证可用的归档路径。

**类型**：`external_system`（客户端）；旧页 frontmatter 记为 `kind: other`。

# 关键属性 / 配置

| 项 | 值 |
| --- | --- |
| 提供商（旧页记录） | 内置 `deepseek-official` |
| 界面实际读取的 provider（新页记录） | `llm-deepseek`（另一套 `llm-pi-ai` 不决定界面展示） |
| 接入点 / Base URL | `llm-deepseek.config.baseURL = http://127.0.0.1:8096/dsh/default`（**不加** `/v1`） |
| 凭据 | Memory 平台的 `user_key` |
| 模型 | `deepseek-v4.1-flash-1017`；默认模型可设为 `auto/deepseek-v4.1-flash`（routing group，`contextWindow: 1000000`，`inputModalities: [text, image]`） |
| 可选模型数 | 2 → **66**（2026-11-10 追加 [[Magpie]] 模型后） |
| 配置文件 | `~/.dsh/profiles/desktop/cordis.patch.yml`，会被 `~/.dsh/settings.yaml` 覆盖 |
| 关键字段名 | `inputModalities`（列表）；`llm-pi-ai` 用的是 `input` |
| 初始化表单 | 选择 `applesay` → `sdp-tag-doc` |
| MCP 接入 | 可在 `~/.dsh/profiles/desktop/cordis.patch.yml` 追加 `mcpServers`（若该版本支持 MCP 配置段），接入 [[Team Brain MCP]]，该通道**不经过 8096** |

会话与记忆通道补充：

- 会话内可绑定 Memory Agent，触发 [[Chat Memory]] 自动提炼。
- 会话内通过 Proxy 的 `memory-bridge` / `skill-bridge` 取记忆与 Skill 列表（依赖 `x-conversation-id`）。
- 配置覆盖层：`~/.dsh/settings.yaml` 优先级高于 `cordis.patch.yml`，且可能在重启时被重写（见 [[DSH 双 Provider 体系与设置覆盖层]]）。
- 2026-11-10 追加 [[Magpie]] 模型后，可选模型由 2 个增至 66 个。

配置示例：

```yaml
- id: llm-deepseek
  name: "@deepseek-ai/dsh-llm-deepseek-api-key"
  config:
    baseURL: http://127.0.0.1:8096/dsh/default      # 走 Memory Proxy
    models:
      - id: deepseek-v4.1-flash-1017
        …
      - id: auto/deepseek-v4.1-flash                 # ← 追加 Magpie 模型
        name: DeepSeek V4.1 Flash · routing group
        contextWindow: 1000000
        inputModalities: [text, image]
```

可选默认模型：

`agent-default-model.config = { provider: deepseek-official, model: auto/deepseek-v4.1-flash, reasoningEffort: high }`

# MCP 接入（2026-11-10）

在 `~/.dsh/profiles/desktop/cordis.patch.yml` 中追加 MCP server（**若该版本支持 MCP 配置段**）：

```yaml
mcpServers:
  team-brain:
    command: node
    args: ["D:/workplace/TencentDB-Agent-Memory-local/team-brain-mcp/dist/mcp/server.js"]
    env:
      MEMORY_USER_KEY: "sk-mem-xxxx"
      MEMORY_TEAM_ID: "team-xxxx"
```

这样 DSH 内的 agent 即可用上 [[Team Brain MCP]] 的 19 个只读工具（Wiki / 代码图谱 / Chat Memory / Skill），且该通道**不经过 8096**。

# 术语差异 / 待确认

- 旧页记录提供商为内置 `deepseek-official`；新页记录界面实际读取的 provider 为 `llm-deepseek`，而默认模型配置仍写 `provider: deepseek-official`。
- 两者可能分别指配置段/插件标识与模型供应商标识，尚未完全统一；此处保留两种说法，实际修改时需同时核对 `llm-deepseek` 配置段与默认模型配置中的 `provider` 字段。

# 已验证 / 未验证

- 已验证：内置提供商的表单与模型回复跑通（用户确认）。
- 已验证：自动归档路径应使用内置提供商。
- 已验证：2026-11-10 在 `llm-deepseek` 下追加 Magpie 模型后，可选模型由 2 个增至 66 个。
- 待确认：MCP 接入取决于当前 DSH 版本是否支持 `mcpServers` 配置段；按接入指南，接入后走 stdio 子进程，不经过 8096。
- 踩坑：旧模型名 `deepseek-flash` 曾被上游拒绝。
- 踩坑：自定义提供商能转发模型请求，但缺少 Memory 绑定所需的 DSH 会话 ID，轨迹落在 `_unassigned`。
- 已知问题：间歇性 `DeepSeek Messages request failed (502)`，见 [[Proxy 转发故障分段定位]]。

# 常见坑

- **改错 provider 体系**：改 `llm-pi-ai` 的 providers 界面纹丝不动，因为界面读的是 `llm-deepseek`。见 [[DSH 双 Provider 体系与设置覆盖层]]。
- **设置被覆盖**：`~/.dsh/settings.yaml` 优先级高于 `cordis.patch.yml`，重启时可能被界面状态重写；改完需确认 `settings.yaml` 中**不含** `llm-deepseek` 段。
- **模型 id 写法**：建议用 [[Magpie]] 规范 id（如 `auto/deepseek-v4.1-flash`），见 模型 ID 解析与路由组。
- **MCP 配置段支持不确定**：追加 `mcpServers` 前需确认当前 DSH 版本支持该配置段；不支持时追加无效。

# 关系

- 与 [[Memory Proxy]]：经 `8096/dsh/default` 接入；上游可继续到 [[Magpie]] → [[applesay 上游模型服务]] 等。
- 与 [[Memory Agent]]：新会话初始化时绑定 `applesay → sdp-tag-doc` → [[项目记忆归属与 Agent 分配]]。
- 与 [[Chat Memory]]：绑定会话满足条件时自动提炼。
- 与 [[会话重置与 Agent 切换]]：同一会话内切换 Agent 需 `mem:session-reset`。
- 与 [[凭据分层模型]]：客户端只填 `user_key`。
- 与 [[Codex Desktop]]：对比——后者保留官方供应商、直连 OpenAI 官方、不经过 Proxy；也是另一客户端，接入方式不同。
- 与 [[DSH 双 Provider 体系与设置覆盖层]]：`llm-deepseek` 与 `llm-pi-ai` 的配置差异及设置覆盖层。
- 与 模型 ID 解析与路由组：模型 id 建议使用 [[Magpie]] 规范 id（如 `auto/deepseek-v4.1-flash`）。
- 上游链路：[[Memory Proxy]]（模型 + 记忆注入）→ [[Magpie]] → 上游模型服务。
- 检索侧：[[Team Brain MCP]]（stdio 子进程）→ [[Memory Knowledge]] / [[Memory Hub]]。

# 回滚

`cordis.patch.yml.bak.20261110`（原始）、`cordis.patch.yml.bak2.20261110`（首次改动前）。

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §3.5、§3.6、§4.4、§4.5、§7、§8
- `memory-hub-magpie-级联配置手册.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §3

# MCP 接入（2026-11-10 查证，修正上文）

**DSH 不使用 `mcpServers` 配置块，也没有独立的 mcp 配置文件**；上文“若该版本支持 MCP 配置段”的方案不成立。DSH 是 Cordis 插件框架，MCP 经 `@deepseek-ai/dsh-mcp-client` 插件接入：

- 配置写入 `~/.dsh/profiles/desktop/cordis.patch.yml` 的**顶层 entry 列表**（与 provider 覆盖配置同一写入方）
- 一个插件实例对应一个 MCP server
- `serverName` 需匹配 `^[A-Za-z0-9_-]{1,32}$`
- 注册后工具名形如 `mcp__team_brain__wiki_search`；重启 DSH 后工具列表应出现 19 个 `mcp__team_brain__*` 工具

完整 schema、模板与三个坑见 [[DSH Cordis 插件式 MCP 接入]]。

# 链路端口补充

- 上游模型链路：DSH → 8096 [[Memory Proxy]] → 3425 [[Magpie]]
- 只读检索链路：DSH 拉起的 [[Team Brain MCP]] 子进程 → 8424 / 8125（平行于模型链路，不经 8096）

# 待确认（新增）

`~/.dsh/settings.yaml` 优先级高于 `cordis.patch.yml` 且可能在重启时被重写——**MCP 的插件 entry 是否也会被冲掉，尚待验证**。

# 关系补充

- 归档路径的性质见 [[记忆沉淀策略]]、[[会话重置与 Agent 切换]]。
