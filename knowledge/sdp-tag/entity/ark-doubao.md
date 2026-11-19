---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/ark-doubao
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/ark-决策模型-doubao.md
  type: wiki
supersedes: []
tags:
- 模型
- 外部服务
- 选型
tier: canonical
title: Ark 决策模型（doubao）
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-10-22 接入的 doubao 决策模型，接入后准确率 −12pp、召回 +8pp；10-27 确认正式打标方案为 doubao 0.8/0.999。

# 定义

Ark 平台上的 doubao 模型，在打标链路中承担**决策**角色（区别于判分角色 [[判分模型 qwen3.8-flash]]）。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 接入日期 | 2026-10-22 |
| 接入效果 | 准确率 **−12pp**，召回 **+8pp** |
| 正式方案 | doubao 0.8 / **0.999**（2026-10-27 确认） |
| label 阈值 | 0.999（历史方案层，见 [[阈值分层]]） |

# 解释要点

准确率下降 12pp 同时召回上升 8pp 是**阈值/取舍变化**的典型表现，不能单独当作模型变差：它对应「宁可多打」的策略转向，而正式方案最终取 0.999 的高阈值。引用该数字时必须按 [[引用标注规范]] 标注样本与口径。

# 关系

- 宿主链路：[[正式打标链路]]
- 阈值分层：0.999 属「历史 doubao 方案」层（对比 lab 0.7、pipeline 0.9）
- 与 [[判分模型 qwen3.8-flash]] 分工不同：决策 vs 判分

# 待补

模型选型（决策模型 / 判分模型是否合并为一份选型文档）需后续来源展开；当前两页分立。

# Citations

- `00-时间线与仲裁口径.md` §1 时间线 10-22、10-27 条目；§3 错 4
