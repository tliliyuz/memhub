---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tagworkflowservice
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tagworkflowservice.md
  type: wiki
supersedes: []
tags:
- 模块
- 阶段编排
- 打标
- 编排
- 阶段
- 维度阶段删除
tier: canonical
title: TagWorkflowService
updated_at: '2026-11-18T07:26:22Z'
---

> 打标阶段编排的权威实现；当前为 scene → label 两阶段，dimension 阶段已退化/移除（直接传参抛异常）。

# TagWorkflowService

## 定义

打标任务的阶段编排模块，决定执行哪些阶段。`TagWorkflowService.java` 定义打标流程的阶段序列，是判断「当前有几个阶段」的唯一代码依据；当前实现为 `scene → label` **两阶段**，`dimension` 阶段已退化/移除。

## 关键属性（代码可验证）

```java
// TagWorkflowService.java
:60  if (stage == LabStage.DIMENSION) throw new ServiceException("独立维度判断已移除");
:78  if (MODE_FULL.equals(mode)) return List.of(LabStage.SCENE, LabStage.LABEL);
```

- 2026-10-26 `69f77f1` 合入：独立「维度阶段」删除，只剩 `scene → label`，见 [[打标阶段模型]]。
- 直接对 `LabStage.DIMENSION` 传参调用会抛异常；「维度阶段」在代码里是异常而非空实现。
- 2026-11-05 重构后，实验台与线上共用同一条代码路径（`lab = production path`）。

| 项 | 内容 |
| --- | --- |
| 当前阶段 | `scene → label`（两阶段） |
| 代码位置 | `TagWorkflowService.java:60`、`:78` |
| 退化的阶段 | `dimension`（老 Spec 称 vestigial/legacy） |
| 路径合并 | 2026-11-05 重构后实验台与线上合并为同一条代码路径 |

## 冲突与裁决

**A2：阶段到底几个？**

| 说法 | 来源 | 时间 |
| --- | --- | --- |
| 只有 `scene → label` 两阶段 | `[C]` `[D]` | 11-05 起 |
| 3 stages: scene / dimension / label | `[D]` 部分 | 11-02 ~ 04 |
| 「dimension stage vestigial/legacy」 | `[Z]` | 10-30 |

**裁决：不是矛盾，是演进**，代码可验证。独立「维度阶段」已于 2026-10-26 `69f77f1` 删除，当前只剩 `scene → label` 两阶段；新资料亦以「退化/移除」描述该阶段。详见 [[打标阶段演进]]。

## 已失效结论

- **B15**：「lab 三阶段」——2026-10-26 `69f77f1` 起为两阶段。
- **B7**：「实验台与线上是两套代码路径」——2026-11-05 重构后已合并成同一条。
- **B16**：「旧 chat_v1 提示词还能跑」——2026-10-21 `502b975` 后只剩审计价值，`LabQuestions.validateTemplate` 会拒（提示词校验归属见 [[打标阶段演进]]）。

## 关系

- 与 [[维度]] 概念区分：阶段删除 ≠ 维度概念消失（维度定义、维度阈值、维度门仍存在）。
- 影响 [[重跑动作体系]]：任务级重跑等于从场景阶段整体重跑。
- [[打标阶段演进]] — 阶段序列的演进叙事与引用规则。
- [[维度定义的生命周期]] — 维度定义同时进打标侧与判分侧；`dimension` 阶段退化直接影响定义作用的观察点。
- [[TagLabProperties]] — 合批/合并行为相关的活开关，影响阶段内的批处理。

## 易误解

- 老文档仍写「三段」，实际只有两段；「维度阶段」在代码里是异常而非空实现。
- 冲突表中的「3 stages」是 11-02 ~ 04 的旧状态，不代表当前实现；当前应以代码与 [[打标阶段演进]] 的裁决为准。

## Citations

- `TagWorkflowService.java:60, :78`
- 提交：`69f77f1`（2026-10-26）、`502b975`（2026-10-21）
- 源：`01-术语实义.md` §2 `[Z]`；`06-未决与空白.md` A2、B7、B15、B16、C13。
