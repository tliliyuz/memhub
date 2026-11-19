---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/jev-2758ca
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/jev.md
  type: wiki
supersedes: []
tags:
- 模型
- 外部系统
- 对照基线
- 缺口
tier: canonical
title: JEV
updated_at: '2026-11-18T07:26:22Z'
---

> 同阈值下准确率 85.6 的对照模型，其试验报告不在仓库内，是阈值无法溯源的关键缺口。

# Schema

- **kind**: external_system
- **职责**：作为打标准确率的对照基线模型。

# Definition

JEV 是在同一阈值（0.7）下测得 **85.6%** 准确率的对照模型，也是三个对照模型中最高的一个（doubao 65.2 / qwen 75.7 / JEV 85.6）。

# 关键属性

| 项 | 内容 |
| --- | --- |
| 对照准确率 | **85.6%**（阈值 0.7） |
| 试验报告 | **不在仓库内** |
| 关联缺口 | 0.8/0.8/0.7 阈值的推导依据无法溯源（C12） |

# 为什么重要

`[Z]` 的记录指出：仓库里没有阈值推导记录，Spec 只把 0.8/0.8/0.7 列为「最终决定」，另提到**一份不在仓库里的 JEV 试验报告**。也就是说，这组阈值很可能是从 JEV 试验推出来的，但证据链在库外。见 [[未发现项清单]] C12、[[06-未决与空白]] E10。

# 口径提示

85.6 与 qwen 75.7 的差距看着大，但口径差（strict 68.2 vs inference 88.0，19.8 pp）比模型间差距更大——引用时不能把「换模型」说成首要杠杆。见 [[rubric 判分口径]]。

# Relationships

- [[qwen3.8-flash]]、[[doubao]] — 同批次对照模型。
- [[未发现项清单]] — C12（阈值推导依据缺失）。
- [[评测噪声与可比性]] — 差异显著性判定。

# Citations

- 源：`06-未决与空白.md` D2、C12、E10
