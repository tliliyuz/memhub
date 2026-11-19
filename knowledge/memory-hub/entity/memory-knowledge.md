---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/memory-knowledge
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/memory-knowledge.md
  type: wiki
supersedes: []
tags:
- 服务
- 知识索引
- wiki
- 检索
- knowledge
- 索引
- 只读端点
- '8424'
- mcp 后端
tier: canonical
title: Memory Knowledge
updated_at: '2026-11-18T07:26:22Z'
---

> 监听 8424 的知识索引服务，与 Memory Hub 共用容器 tdai-memory-hub，支撑 Wiki 与知识检索链路（含代码图谱）；其 /v3 只读端点无需密钥，是 MCP 的 Wiki 与代码图谱后端，可用性受 knowledge.enabled 开关控制。

# 定义

`memory-knowledge` 是 [[TencentDB Agent Memory]] 的知识索引服务，与 [[Memory Hub]] 共同支撑 [[Wiki]] 与知识检索链路（含代码索引 / [[Code Graph]]）。它监听 **8424**，并与 [[Memory Hub]] 共用容器 `tdai-memory-hub`（一容器双端口映射：8125 + 8424）。其可用性由 `knowledge.enabled` 开关控制（旧来源记录该开关位于 [[Memory Proxy]] 生成的 `config.yaml` 中，见 [[能力开关显式固化]]）。

对外它提供 **`/v3` 只读端点**，覆盖 wiki 与 code-graph 两类检索，被 [[Team Brain MCP]] 用作 Wiki 与代码图谱的后端。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 容器 | `tdai-memory-hub`（与 [[Memory Hub]] 同容器） |
| 端口 | 8424（面向知识索引；同容器 8125 面向面板 API） |
| 绑定地址 | `127.0.0.1`（见 [[本地部署拓扑与回环绑定]]） |
| 健康检查 | `GET /health` |
| 只读端点 | `/v3`，覆盖 wiki 与 code-graph 两类检索 |
| 鉴权 | `/v3` **无需密钥**即可访问（与面板 8125 的鉴权方式形成对比，见 [[MCP 双后端只读接入]]） |
| 配置开关 | `knowledge.enabled` 必须为 `true`；关闭时 MCP 的 12 个 Wiki/代码图谱工具失效，但 Chat Memory / Skill 不受影响，见 [[能力开关显式固化]] |
| MCP 侧接入 | 环境变量 `KNOWLEDGE_API_URL`（默认 `http://127.0.0.1:8424`）指向本服务 |
| 底层数据 | 落在 [[Memory Core]]（8420） |

# 关系

- 组成：[[TencentDB Agent Memory]] 的四个服务之一（见 [[本地部署拓扑与回环绑定]]）
- 与 [[Memory Hub]]：Hub 负责 Wiki 与知识索引的管理，Knowledge 承担索引服务侧；两者同容器、端口不同（8424 面向知识索引，8125 面向面板 API），共同支撑 Wiki 与知识检索。
- 与 [[Team Brain MCP]]：作为其 **Wiki（4 个工具）与代码图谱（8 个工具）的后端**——`wiki_search` / `wiki_read` / `wiki_list` / `wiki_graph`；`code_search` / `code_explore` / `code_callers` / `code_callees` / `code_impact` / `code_node` / `code_status` / `code_files`（共 12 个）。MCP 通过 `KNOWLEDGE_API_URL`（默认 `http://127.0.0.1:8424`）指向它。
- 与 [[MCP 双后端只读接入]]：是其「免密钥」那一侧的后端——`/v3` 无需密钥，是 [[Team Brain MCP]] 能把 Wiki 与代码图谱工具暴露给任意 agent 的前提。
- 与 [[Memory Core]]：索引数据底层落在 Core（8420）。
- 与 [[Memory Proxy]]：旧来源记录开关由 Proxy 生成的 `config.yaml` 控制；新来源称与 Proxy 的**模型链路无直接耦合**（两者可能分指配置生成与请求链路，见下节差异）。
- 与 [[Wiki Ingest 加工管线]]：索引链路的消费方（推断）
- 检索内容对应 [[Wiki]] 资产与 [[三类资产模型]]。
- 端口/绑定总表见 [[本地部署拓扑与回环绑定]]。

# 差异与待澄清

- **与 [[Memory Proxy]] 的耦合程度**：旧来源称 `knowledge.enabled` 由 Proxy 生成的 `config.yaml` 控制；新来源称与 Proxy 的模型链路无直接耦合。两者未必矛盾（配置生成 ≠ 运行时模型请求链路），但需明确表述边界，暂并列记录。
- **`/v3` 的暴露范围**：旧来源记录 8424 仅绑定 `127.0.0.1`，新来源同样记录绑定 `127.0.0.1` 且 `/v3` 无需密钥。因此「无需密钥」应理解为对本机/同宿主调用方不做鉴权；一旦改为对外暴露，则需重新评估风险。
- **开关影响的描述口径**：旧来源称开关关闭时「记忆链路断开」；新来源将其细化为「MCP 的 12 个 Wiki/代码图谱工具失效，但 Chat Memory / Skill 不受影响」。后者更具体，暂以后者为准，保留旧表述以备考。

# 待补充

具体职责边界（索引粒度、召回方式、与 Core 的索引分工）仍待补。旧来源仅给出端口与「知识索引服务」的定性描述；新来源补充了容器、开关、`/v3` 只读端点、调用方工具清单与 `KNOWLEDGE_API_URL` 接入方式，但仍未说明索引粒度与召回方式。

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §2、§3.3
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §1、§2、§5、§7
