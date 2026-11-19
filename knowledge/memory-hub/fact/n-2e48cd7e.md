---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/n-2e48cd7e
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/三类资产模型.md
  type: wiki
supersedes: []
tags:
- 资产模型
- 记忆组织
- 记忆资产
- 数据模型
- mcp
- 工具映射
tier: canonical
title: 三类资产模型
updated_at: '2026-11-18T07:26:22Z'
---

> Chat Memory / Wiki / Skill 各自有「对话中怎么用」和「怎么更新」两套规则；2026-11-10 起新增 MCP 只读检索第三条通道，19 个工具与四类资产（含 Code Graph）一一对应。

# 定义

[[TencentDB Agent Memory]] 把团队知识分成三类记忆资产，每类都有**「对话中怎么用」**与**「怎么更新」**两套规则：

| 资产 | 在对话中怎么用 | 怎么更新 |
| --- | --- | --- |
| [[Chat Memory]] | [[Memory Proxy]] 提供 L3 长期画像与 L2 场景索引；Agent 按需下钻 L2 正文、L1 原子记忆、L0 原始会话 | 会话绑定 Agent 后**自动提炼**；也可导入历史。新证据可更新同一 L2 场景，时间流逝不触发更新 |
| [[Wiki]] | Agent 搜索已分配 Wiki，再读取命中页面；需先分配给项目，就绪后可检索 | 上传选定源材料后触发 **Ingest**（见 [[Wiki Ingest 加工管线]]）；面板要求 Wiki 就绪后才能分配；会话记忆**不会**自动写入 Wiki |
| [[Skill]] | [[Memory Proxy]] 提供可用列表，Agent 用到时读取完整步骤；MCP 亦提供只读列表 | 可从会话中提炼，也需显式维护，适合可重复的排查/验证/操作流程 |

此外，[[Code Graph]] 作为**第四类资产（代码结构）**存在，存放在 [[Memory Knowledge]] 中（详见下文「Code Graph」一节，其定位在旧页与新页间存在表述差异）。

划分资产的目的不是分类学，而是**给每类资产找到正确的更新触发点**：会话驱动的自动沉淀、人工上传的加工管线、从经验中提炼的流程。

## 版本差异说明

- **Wiki 分配与就绪顺序**：旧页记载「面板要求 Wiki 就绪后才能分配」；新页记载「需先分配给项目、就绪后检索可用」。两版对「就绪」与「分配」的先后顺序表述不一致，均保留，待后续来源核实。
- **Chat Memory 下钻层级**：旧页明确包含 L1 原子记忆；新页仅列 L2 正文与 L0 原文。合并后保留 L1 作为可用下钻层级，不视为删除。
- **Skill 更新方式**：旧页强调可从会话中提炼；新页补充「也需显式维护」，二者兼容。
- **Code Graph 的定位**：旧页称其为「可选能力」，不属于三类资产，且「当前使用方式可先跳过」；新页将其列为**第四类资产**（代码结构），并给出 8 个 MCP 工具。两版对 Code Graph 是否属于「资产」表述不一致，均保留：既承认其可作为第四类资产被 MCP 检索，也保留「可选能力、可先跳过」的使用建议，待后续来源核实。

## 第三条通道：MCP 只读检索（2026-11-10 起）

在此之前，agent 只能通过 [[Memory Proxy]]（会话内注入）或面板人工操作接触这些资产。[[Team Brain MCP]] 新增了一条**平行于模型链路、不经过 Proxy 的只读检索通道**，19 个工具与四类资产严格对应：

| 资产 | 工具数 | 工具 | 后端 |
| --- | --- | --- | --- |
| [[Wiki]] | 4 | `wiki_search` / `wiki_read` / `wiki_list` / `wiki_graph` | [[Memory Knowledge]] 8424 `/v3`（无密钥） |
| [[Code Graph]] | 8 | `code_search` / `code_explore` / `code_callers` / `code_callees` / `code_impact` / `code_node` / `code_status` / `code_files` | 存放于 [[Memory Knowledge]]（新页仅说明存放位置，具体端点未记载，待核实） |
| [[Chat Memory]] | 5 | `chat_memory_agents` / `chat_memory_search` / `chat_memory_layer` / `chat_memory_list` / `chat_memory_stats` | [[Memory Hub]] 8125 `/api/v1`（`sk-mem` 密钥） |
| [[Skill]] | 2 | `skill_search` / `skill_read` | [[Memory Hub]] 8125 `/api/v1`（`sk-mem` 密钥） |

要点：

- **Skill 的可用列表来源从 Proxy 扩展到 Panel**（8125），因此不再要求活跃会话。
- **只读**是硬约束：写入/分配/ingest 仍归控制面，MCP 不暴露。
- 概念细节见 [[MCP 双后端只读接入]]。

# Skill（详见本节，暂不单独立页）

Skill 是**可复用操作流程资产**：[[Memory Proxy]] 提供可用列表，Agent 在需要时读取完整步骤；可从会话中提炼，也需显式维护。适用于可重复执行的排查、验证或操作流程。MCP 接入后，可用列表来源扩展到 Panel（8125），不再要求活跃会话；MCP 提供 `skill_search` / `skill_read` 两个只读工具。源文档信息仍有限，待后续来源补充后再考虑拆分独立页面。

# Code Graph

[[Code Graph]] 用于预先索引符号与调用关系。旧页称其为**可选能力**，[[DSH Desktop]] 能直接读取当前工作目录，当前使用方式可先跳过；新页则将其列为**第四类记忆资产**（代码结构），存放在 [[Memory Knowledge]]，并通过 MCP 暴露 8 个只读工具（`code_search`、`code_explore`、`code_callers`、`code_callees`、`code_impact`、`code_node`、`code_status`、`code_files`）。两种表述并存：可按需选用，也可直接依赖 [[DSH Desktop]] 读取工作目录。

# 意义

- 区分「被动自动沉淀」（Chat Memory）与「主动投喂加工」（Wiki），避免误以为对话会自动进 Wiki。
- Skill 介于两者之间：可从会话提炼，但以可执行流程为单位。
- MCP 为各类资产提供统一的 agent 只读检索通道（19 个工具），同时将写入/分配/ingest 保留在控制面。
- 分类的真正目的是**为每类资产找到正确的更新触发点**：会话驱动的自动沉淀、人工上传的加工管线、从经验中提炼的流程。

# 相关实体

[[Chat Memory]]、[[Wiki]]、[[Skill]]、[[Code Graph]]、[[Wiki Ingest 加工管线]]、[[Memory Proxy]]、[[Team Brain MCP]]、[[记忆分层 L0–L3]]、[[Memory Hub]]、[[Memory Knowledge]]、[[MCP 双后端只读接入]]

相关概念：

- [[记忆沉淀策略]] —— 哪些知识值得沉淀进这些资产
- [[记忆分层 L0–L3]] —— Chat Memory 的内部结构
- [[项目记忆归属与 Agent 分配]] —— 资产的归属维度

# Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §1
