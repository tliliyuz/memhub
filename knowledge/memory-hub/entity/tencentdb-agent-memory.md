---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: memory-hub/entity/tencentdb-agent-memory
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/tencentdb-agent-memory.md
  type: wiki
supersedes: []
tags:
- 平台
- 记忆平台
- 记忆
- 本地部署
- 架构
tier: canonical
title: TencentDB Agent Memory
updated_at: '2026-11-18T07:26:22Z'
---

> 本地部署的整体记忆平台，由 Hub、Core、Knowledge、Proxy 四个服务组成，负责记忆沉淀并向客户端提供统一入口；2026-11-10 起上游经 Magpie 级联，并新增面向 agent 的只读出口 Team Brain MCP。

# 定义

`tencentdb-agent-memory` 是本机部署的整体记忆平台，由 [[Memory Hub]]、[[Memory Core]]、[[Memory Knowledge]]、[[Memory Proxy]] 四个服务组成，负责把团队对话、会话与源材料沉淀为可检索、可复用的记忆资产，并向 AI 客户端提供统一的模型/记忆入口。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 源码仓库 | `D:\workplace\TencentDB-Agent-Memory`（分支 `feat/server_team`，提交 `2002196`） |
| 本地部署副本 | `D:\workplace\TencentDB-Agent-Memory-local` |
| 启动方式 | `start-local.sh` |
| 部署前置 | Git Bash + Docker Desktop |
| 部署形态 | 单机 Docker Desktop + 宿主机常驻进程，见 [[本地部署拓扑与回环绑定]] |
| 入口面板 | http://127.0.0.1:8125/ |
| 服务组成 | Proxy(8096) / Hub(8125) / Knowledge(8424) / Core(8420) |
| 对外出口 | 面板 8125（人）/ Proxy 8096（模型请求）/ [[Team Brain MCP]]（agent 只读检索） |
| 客户端凭据 | Memory 平台的 `user_key` |
| 上游模型（旧记录） | `https://applesay-api-hup.applesay.cn/v1`，模型 `deepseek-v4.1-flash-1017` |
| 模型上游（新记录） | **2026-11-10 起**经 [[Magpie]] 级联；此前直连 [[applesay 上游模型服务]] |
| 记忆分层 | [[记忆分层 L0–L3]]（L0 原文 / L1 原子 / L2 场景 / L3 画像） |
| 资产类型 | [[Chat Memory]]、[[Wiki]]、[[Skill]]，见 [[三类资产模型]] |

# 组成

- [[Memory Hub]]（8125）— 面板与 Wiki/知识索引管理
- [[Memory Core]]（8420）— 核心服务，SQLite + Docker 卷 `tdai-memory-core-data`
- [[Memory Knowledge]]（8424）— 知识索引服务
- [[Memory Proxy]]（8096）— 模型/能力代理，向上游转发并暴露记忆索引

# 面向 agent 的统一读取出口（2026-11-10）

[[Team Brain MCP]] 成为平台的**第三个对外面**：前两个是面向人的面板（[[Memory Hub]] 8125）与面向模型请求的代理（[[Memory Proxy]] 8096），MCP 则是**面向 agent 的只读检索出口**——19 个工具覆盖 Wiki / 代码图谱 / Chat Memory / Skill，且不参与模型转发。

这意味着平台的能力矩阵变为：

| 面 | 面向 | 能力 |
|---|---|---|
| 面板 8125 | 人 | 分配、就绪校验、Ingest、运维查询 |
| Proxy 8096 | 模型请求 | 记忆注入、L0 落库、模型转发 |
| MCP（stdio） | agent | 只读检索（团队大脑） |

# 上游变更与记录差异

- 旧页面记录：上游模型为 `https://applesay-api-hup.applesay.cn/v1`，模型 `deepseek-v4.1-flash-1017`，经 [[Memory Proxy]] 转发，凭据由服务端持有 → [[凭据分层模型]]。
- 新页面记录：**2026-11-10 起**模型上游经 [[Magpie]] 级联；此前直连 [[applesay 上游模型服务]]。
- **记录不一致**：旧记录描述为直连 applesay，新记录描述为经 Magpie 级联（并注明 2026-11-10 前直连）。两条记录均保留；实际以部署时间与当前配置为准。

# 新增的外部依赖

改为级联后，平台多了一层外部依赖 [[Magpie]]（宿主机进程 `magpie.exe`，3425）。这意味着：

- 平台可用性依赖 Magpie 进程存活（容器内可通过 `host.docker.internal:3425` 探测）。
- 模型自由度的提升（DSH 可选模型 2 → 66）来自 Magpie，而非平台自身。
- 记忆链路本身仍由 Proxy 的能力开关决定，与 Magpie 无关（见 [[能力开关显式固化]]）。

# 关系

- 与 [[applesay 上游模型服务]]：旧记录为经 [[Memory Proxy]] 直连转发，凭据由服务端持有 → [[凭据分层模型]]；新记录为 [[Memory Proxy]] → [[Magpie]] → applesay 等上游。
- 与客户端：[[DSH Desktop]]（内置提供商接入 Proxy）、[[Codex Desktop]]（官方供应商 + 会话导入）。
- 与 agent：[[Team Brain MCP]] 提供只读检索出口，覆盖 Wiki / 代码图谱 / Chat Memory / Skill，不参与模型转发。
- 与记忆组织：[[Memory Agent]] 决定记忆的读取与沉淀，归属由 [[项目记忆归属与 Agent 分配]] 定义。
- 部署形态：[[本地部署拓扑与回环绑定]]。
- 记忆资产：[[Chat Memory]]、[[Wiki]]、[[Skill]] → [[三类资产模型]]。
- 拓扑原则见 [[级联代理拓扑与分层顺序]]。

# 已知问题

- [[Proxy 转发故障分段定位]]：DSH 间歇性 502，故障段在 Proxy → 上游。
- 改为级联后，Magpie 进程存活成为平台可用性的前置条件；容器内可用 `host.docker.internal:3425` 探测。

# Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `memhub-magpie-级联配置手册.md` §1、§2、§7
- `memory-hub-magpie-级联配置手册.md` §1、§7
- `team-brain-mcp-接入指南.md` §1、§7
