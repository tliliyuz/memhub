---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/judge-bc2ae9
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/生产-judge-模型.md
  type: wiki
supersedes: []
tags:
- judge
- 模型
- 阈值
tier: canonical
title: 生产 judge 模型
updated_at: '2026-11-18T07:26:22Z'
---

> 正式打标链路使用的 judge 模型配置，2026-10-29 由 doubao 0.999 切换为 qwen3.8-flash 0.9。

# 定义

生产 judge 模型是正式打标链路评分使用的 LLM 配置。模型与阈值**成对**决定，切换模型必须重定阈值。

# 配置表

| 模型 | provider / kind | 上线时间 | label 阈值 | 实测准确率 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `doubao-seed-2-1-lite-260915` | ark / systemone，128k | 2026-10-27（`d434c38`） | 0.999（scene 0.8） | 0.7 = 65.2%（854 矛盾）；0.999 = **80.1%**（3,307 正确 / 365 矛盾，post-hoc 回放） | **已被取代**（仅在「恢复 doubao」时适用） |
| `qwen3.8-flash` | — | 2026-10-29 | **0.9** | 0.7 = 75.7%；0.9 = **92.4%**（79 件） | 当前生产 |

对照基线：[[JEV 推理服务]] 0.70 阈值下两阶段准确率 85.6%——**doubao 0.999 仍低于该基线**。

# 关键属性

- **一模型一全局阈值**：报告 §6.14 评估过分维阈值，**被否决**，见 [[全局阈值 vs 分维阈值]]。
- **阈值语义变化风险**：若改由模型门控，输出分数整体上移 +0.058，阈值语义被改写，见 [[模型门控 vs 服务端阈值筛选]]。
- **成本**：全量回刷前需确认数量/token/费用。

# 关系

- 经 [[JEV 推理服务]] / Ark 调用；服务于 [[打标系统]]。
- 评估依赖 [[评估样本集]] 与 [[砍标签类改动的评估口径]]。

# Citations

- `02-方案选型与权衡.md` §20
