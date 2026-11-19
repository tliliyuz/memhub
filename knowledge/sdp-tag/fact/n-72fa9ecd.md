---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-72fa9ecd
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/维度.md
  type: wiki
supersedes: []
tags:
- dimension
- 图谱
- 维度定义
tier: canonical
title: 维度
updated_at: '2026-11-18T07:26:22Z'
---

> 图谱二级节点（147 个，快照 141 个），名字全局唯一需行业前缀；维度定义经历四段状态变化。

# 维度

## 定义（实义）

[[知识图谱]] 的二级节点，当前 147 个（冻结快照 141 个）。字段：`name` / `dimension_definition` / `label_threshold`。

**重大口径变化**：独立的「维度阶段」已被取消（2026-10-26 `69f77f1` 合入）`[Z]`，见 [[TagWorkflowService]]、[[打标阶段模型]]。

```java
:60  if (stage == LabStage.DIMENSION) throw new ServiceException("独立维度判断已移除");
:78  if (MODE_FULL.equals(mode)) return List.of(LabStage.SCENE, LabStage.LABEL);
```

但「维度」这个词仍到处用——维度定义、维度阈值、维度门。**阶段没了 ≠ 维度概念没了。**

## 维度定义的状态（直接影响实验解读）

| 时间 | 状态 |
| --- | --- |
| ~10-20 | 全空。**4,692 个标签 remark 全 NULL**，`dimension_definition` 也空 `[Z]` |
| 10-26 09:21 | [[图谱团队]] 重写 140 个维度定义 `[Z]` |
| 10-26 19:09 → 10-27 12:06 | 有过一版「精简版」 |
| 10-27 12:06 之后 | **全部置 NULL（清空）** `[Z]` |

⚠️ 10-26~10-27 那批实验测的是**「定义清空」**，不是「精简」 `[Z]`。这直接影响对后来「补定义」实验的解读，也与 [[证据]] 里「90.0% 是双盲基线」的结论互为因果。

## 易误解

- 维度名**全局唯一**（`uk_graph_dimension_name`），两个行业若有同义维度必须靠行业前缀改名 `[D]`。
- **48 个维度是 0 标签**（宠物 12、美妆护肤 9、服装 9…），有些还能通过门禁然后什么都不问 `[Z]`。
- 维度阈值是「替换」而非叠加，见 [[阈值体系]]。

## 验证方式

- 查 `graph_dimension` 行数与 `label_threshold` 分布。
- 检查 `dimension_definition` 是否为 NULL 批次，以判定实验上下文。

## 相关页面

[[场景]] · [[标签]] · [[门控]] · [[阈值体系]] · [[TagWorkflowService]]

## Citations

- `01-术语实义.md` §2 `[D][Z]`。
