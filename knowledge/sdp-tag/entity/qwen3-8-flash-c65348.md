---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/qwen3-8-flash-c65348
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/判分模型-qwen3-8-flash.md
  type: wiki
supersedes: []
tags:
- 模型
- 判分
- 评测
tier: canonical
title: 判分模型 qwen3.8-flash
updated_at: '2026-11-18T07:26:22Z'
---

> 承担 llm.judge 的判分模型，2026-10-29 由原模型切换到 qwen3.8-flash，label 阈值同步由 0.7 提到 0.9。

# 定义

`llm.judge` 是打标评测中的自动判分组件；2026-10-29 其模型切换为 **qwen3.8-flash**。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 接入日期 | 2026-10-29 |
| 角色 | 判分（`llm.judge`），非决策 |
| 阈值联动 | label 阈值同步由 0.7 → **0.9** |
| 口径 | 与 [[判分口径]] `lab-accuracy-v3-inference`（10-27 起默认）配合使用 |

# 注意

- 判分模型给出的分数是「评测口径」的一部分，引用任何由它产出的准确率必须写明模型名与日期（见 [[引用标注规范]]）。
- 10-29 的阈值 0.7 → 0.9 属「实验台 → 正式」迁移期的联动，**不要与 [[阈值分层]] 中三层默认值混淆**。
- 人工流程层为 [[官方评测标准]]（双评 + 分歧仲裁），与自动判分是不同层。

# 关系

- 服务对象：[[商品打标实验台]] 的评测
- 对照实体：[[Ark 决策模型（doubao）]]（决策角色）

# Citations

- `00-时间线与仲裁口径.md` §1 时间线 10-29 条目；§5 引用格式示例
