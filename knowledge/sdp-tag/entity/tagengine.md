---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tagengine
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/打标引擎-tagengine.md
  type: wiki
supersedes: []
tags:
- 打标系统
- 核心模块
tier: canonical
title: 打标引擎（TagEngine）
updated_at: '2026-11-18T07:26:22Z'
---

> 正式打标链路的核心执行模块，逻辑从实验台（lab）抽取而来，与 lab 共用同一套打标能力。

# 定义

kind: module

打标引擎负责商品打标的实际执行：组织提示词、派发批次、收集标签、回写结果。其核心逻辑最初存在于 [[实验台（lab）]]（`TagLabServiceImpl`）中，后被抽取到 `TagEngine`，成为正式链路与实验链路共用的执行核心。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| `maxBatchRetries` | 实验链路传入 **0**（正式链路才是 2）→ 一次 429 就让整件商品重来（B7） |
| `requestTokenLimit` | 提示词 token 上限控制点，超限即需拆分批次 |
| `stagesOf` / `batchStateOf` / `hitDimensions` 移除 | 与 lab 分裂后必须人工移植的逻辑点（D15） |
| 提示词长度敏感性 | 受 [[打标提示词（label 版本）]] 版本影响：label v11 使单题约 341 字符、整包估算 81,317 token → 触发 64k 超限 |
| 规则打标 | `rule_tagger_code` 字段存在但**无执行实现**（A8 的价格方案 D 因此未落地） |

# 关系

- ← 逻辑来源：[[实验台（lab）]]；两者分裂后每次合并都有分歧风险。
- ↔ [[Judge 判定模型]]：打标与判定是**两套口径**，定义类改动必须同时验证「模型是否照做」与「Judge 是否照判」。
- ↔ [[打标提示词（label 版本）]]：提示词版本决定单题长度、token 与副作用面。
- → [[消息队列 / 阿里云 Serverless AMQP]]：批次失败/超时最终表现为 reject（无 DLX 时即丢失）。
- ↔ [[幂等键与缓存指纹]]：`tagged_input_hash` 由引擎侧写入，为 NULL 会导致全量重打（约 18.7 万 token/件）。

# 已知问题

- **合并陷阱（D15，重复踩过两次）**：本地把 lab 逻辑抽到 `TagEngine`，远端仍在改 `TagLabServiceImpl`，Git 会把远端编辑「干净地」合进**死代码**。因此 `stagesOf`、`hitDimensions` 移除、`requestTokenLimit`、`batchStateOf` 都要手工移植。**规矩：每次与远端合并后，diff `TagEngine` 与远端在 `TagLabServiceImpl` 里的改动。**
- 实验链路 `maxBatchRetries=0`（B7）被点名为「最该修的低效点」。
- 阶段性结果被当成功（G2/G3），详见 [[已知未修缺口清单]]。

# Citations

- A8、B7、B10、D15、G4；出处见 [[03-失败与被推翻]]。
