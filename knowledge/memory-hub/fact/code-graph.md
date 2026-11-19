---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/code-graph
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/code-graph.md
  type: wiki
supersedes: []
tags:
- 代码索引
- 检索
- mcp
- 可选能力
- code-graph
- 资产
- 代码检索
tier: canonical
title: Code Graph
updated_at: '2026-11-18T07:26:22Z'
---

> 预索引的符号与调用关系能力，存放在 Memory Knowledge 中供只读查询；早期因 DSH 可直接读工作目录而被跳过，2026-11-10 起已通过 Team Brain MCP 的 8 个代码图谱工具对外可用，可用性受 knowledge.enabled 开关控制。

# Code Graph

## 定义

Code Graph（代码图谱）是 [[TencentDB Agent Memory]] 体系中的一项能力，用于对仓库做**预索引**，得到符号与调用关系图，供 Agent 检索。索引结果存放在 [[Memory Knowledge]]（8424）中，通过 `/v3` 只读端点查询，可用于「不看源码也能定位符号、调用方、被调方与影响面」。

它回答的是「这个符号在哪、被谁调用、改了会影响什么」，而不是全文搜索。

在旧版描述中，该能力被定位为**可选**能力：它虽然与 [[三类资产模型]] 并列提及，但不属于 Chat Memory、Wiki、Skill 这三类核心资产。（新页面的标签体系把它归入「资产」，与旧页「不属于三类核心资产」的定位存在措辞差异，此处并存记录：它是一项可选的图谱类资产，而非三类核心资产之一。）

## 意义

- 为 Agent 提供**结构化的代码检索**能力：跨文件查找定义、追调用链、评估改动的影响面。
- 让 agent 在**跨仓、跨目录**的场景下也能做影响分析，而不依赖「把整个仓库塞进上下文」。
- 与文本检索（[[Wiki]]）互补：代码图谱回答「代码之间如何连接」，Wiki 回答「为什么这样设计」。

## 当前状态与能力修正

- **旧结论（早期）**：当前使用方式**先跳过**该能力，因为 [[DSH Desktop]] 能直接读取当前工作目录，无需预索引。
- **新结论（2026-11-10 修正）**：上述判断需修正——代码图谱**已通过 [[Team Brain MCP]] 的 8 个工具对外可用**（后端为 [[Memory Knowledge]] 8424 的 `/v3`，无需密钥）。

> 两处记载存在冲突：旧页称「因 DSH 可直接读工作目录而被跳过」，新页称「已通过 MCP 工具对外可用」。二者并存记录：跳过是早期的使用决策，2026-11-10 起能力已实际可调用；是否需要启用仍取决于场景与 [[DSH Desktop]] 直读的取舍。

## 对外读取接口（2026-11-10 起）

[[Team Brain MCP]] 暴露 8 个只读工具：

| 工具 | 用途 |
|---|---|
| `code_search` | 关键词/符号检索 |
| `code_explore` | 探索某节点周边结构（从符号出发探索） |
| `code_callers` | 查调用方（谁调用了它） |
| `code_callees` | 查被调方（它调用了谁） |
| `code_impact` | 评估改动影响面 |
| `code_node` | 取节点详情 |
| `code_status` | 查询索引状态 |
| `code_files` | 列出已索引文件 |

后端是 [[Memory Knowledge]]（8424）的 `/v3` 只读端点，**无需密钥**；可用性受 `knowledge.enabled` 开关控制。见 [[MCP 双后端只读接入]]。

## 待补充

- 索引粒度、构建触发方式、与 [[Memory Knowledge]] 索引的关系，源文档未说明（已知可用性由 `knowledge.enabled` 控制，其余未述）。

## 相关实体

[[TencentDB Agent Memory]]、[[Memory Knowledge]]、[[DSH Desktop]]、[[Team Brain MCP]]、[[MCP 双后端只读接入]]、[[三类资产模型]]、[[Wiki]]、[[Chat Memory]]、[[Skill]]

## 常见主题

系统架构（索引服务位置）、数据流（`/v3` 只读查询）、模块边界（索引 vs 检索 vs 生成）、跨仓跨目录的影响分析

## Citations

- `tencentdb-agent-memory-session.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` 第 1 节
