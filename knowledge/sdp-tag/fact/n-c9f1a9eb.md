---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-c9f1a9eb
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/闸门阈值.md
  type: wiki
supersedes: []
tags:
- 阈值
- 打标
- 静默失败
tier: canonical
title: 闸门阈值
updated_at: '2026-11-18T07:26:22Z'
---

> gateThreshold 高于 dimensionThresholds 时，那部分标签永远不产出且不报错，是「标签数突然少三成」的首查项。

# Definition

打标链路里存在两级阈值：**闸门阈值**（`gateThreshold`）与**维度阈值**（`dimensionThresholds`）。

当 `gateThreshold` 高于 `dimensionThresholds` 时，落在两者之间的那部分标签**永远不产出，且不报错**。

# Significance

- 是「标签数突然少三成」「某维度标签异常少」的**首查项**。
- 是[[静默失败]]的典型形态：没有异常、没有错误日志，只有产出减少。
- 与[[打标四阶段链路]]的关系：场景阶段零命中 → `label=skipped`，看起来像标签阶段问题，实际在场景/闸门层。

# Related entities

[[sdp-tag-api]] · [[tag_task]] · [[标签图谱库]]（维度定义漂移会让阈值口径变化）

# Common topics

- **配置与判定规则**：两级阈值的一致性是正确性前提。
- **评价框架**：阈值可救性见[[分数带与准确率映射]]（<0.80 抬阈值可救，≥0.90 不可救）。

# Citations

- 04 排障信号手册 §0、§3.2、§3.6
