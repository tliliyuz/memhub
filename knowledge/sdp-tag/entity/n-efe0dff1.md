---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/n-efe0dff1
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/标签图谱库.md
  type: wiki
supersedes: []
tags:
- 图谱
- 标签定义
- 评测
tier: canonical
title: 标签图谱库
updated_at: '2026-11-18T07:26:22Z'
---

> 维度与标签定义源，会随版本漂移（6,352→7,440 标签、2026-10-26 重写 140 个维度定义），评测必须显式对齐。

# Definition

维度与标签定义的来源库。评测口径的时间基准，也是一个**会漂移的外部依赖**。

# Key attributes

## 漂移事实

- 标签数 **6,352 → 7,440（+17%）**：**新加的 1,088 个标签在旧分母里不存在**。
- **2026-10-26 09:21 重写了 140 个维度定义**。
- 10-23 改过一个维度定义，并给 tenant 935515 开了 `attr5`。

## 对齐的三种手法

1. **内存还原**：`BeanPostProcessor` 代理 `GraphDimensionMapper` 还原旧定义；代理 `ITagFieldConfigService.listMerged` 去掉后来开的 `attr5`
2. **冻结快照**：从基线导出的 `graph` 块还原变更行
3. **`--reuse-baseline`**：复用旧判定——**但输入指纹不同会拒绝**（「禁止复用」）

## 列名陷阱

- `graph_label.remark`（**没有** `definition` 列，**也不是** `label_remark`）
- `graph_dimension` **没有** `del_flag`

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[评测口径一致性]] | 图谱漂移必须显式对齐才能比较 |
| [[分数带与准确率映射]] | 新标签进入分母后的准确率变化 |
| [[lab-bench]] | 评测执行方 |

# Citations

- 04 排障信号手册 §5.1、§5.2、§6
