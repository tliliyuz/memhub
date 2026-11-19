---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/doubao
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/doubao.md
  type: wiki
supersedes: []
tags:
- 模型
- 外部系统
- 历史配置
tier: canonical
title: doubao
updated_at: '2026-11-18T07:26:22Z'
---

> 历史默认打标模型（阈值 0.999），现仅在恢复场景适用。

# Schema

- **kind**: external_system
- **职责**：历史上正式打标链路的默认大模型；现为回退/恢复用模型与对照基线。

# Definition

`doubao` 曾是正式打标的默认模型，配置阈值 **0.999**。自 2026-10-29 `1cbcabb` 起被 [[qwen3.8-flash]]（阈值 0.9）取代，**现仅在恢复场景适用**。

# 关键属性

| 项 | 内容 |
| --- | --- |
| 历史默认阈值 | **0.999** |
| 现状 | 仅恢复场景适用；非正式打标默认 |
| 对照准确率 | 同 0.7 阈值下 **65.2%** |

# 已失效结论

- **B14**：「doubao 0.999 是正式打标默认」——2026-10-29 `1cbcabb` 后失效。

# 口径提示

65.2 / 75.7 / 85.6（doubao / qwen / JEV @0.7）这组模型间差异**远小于口径差异**（19.8 pp），所以「换模型带来多少提升」这类论断必须先锁定口径。见 [[rubric 判分口径]]。

# Relationships

- [[qwen3.8-flash]] — 取代它的当前默认模型。
- [[jev]] — 同批次对照模型。
- [[评测噪声与可比性]] — 判断该差异是否超出噪声。

# Citations

- 提交：`1cbcabb`（2026-10-29）
- 源：`06-未决与空白.md` B14、D2
