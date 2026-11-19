---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/jev
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/jev-推理服务.md
  type: wiki
supersedes: []
tags:
- 推理服务
- 限额
- 外部系统
tier: canonical
title: JEV 推理服务
updated_at: '2026-11-18T07:26:22Z'
---

> 承载 judge 推理的外部服务，单请求 64k、单题 32k 的限额直接约束批处理与拆批策略。

# 定义

JEV 是打标链路使用的推理服务（judge），承载提示词与商品数据，返回带分数的候选结果。

# 关键属性

- **限额**：单请求 64k token、单题 32k token——这是所有批处理/语义组划分/拆批策略的硬约束。
- **基准对照**：JEV 0.70 阈值下两阶段准确率 85.6%，是 doubao 0.999（80.1%）的对照基线。
- **超限处理**：超过 96k 估算的语义组由 `LabBatchPlanner` 切成最少的连续子请求（见 [[打标系统]]）。

# 关系

- 被 [[打标系统]] 与 [[Lab 实验台]] 调用。
- 与 [[一个语义组一个请求]]、[[取消维度阶段]] 的成本/限额权衡直接相关。
- 与 [[生产 judge 模型]] 是「服务 vs 模型配置」的关系。

# Citations

- `02-方案选型与权衡.md` §11、§12、§20
