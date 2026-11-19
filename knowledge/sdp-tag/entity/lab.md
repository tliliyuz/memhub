---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/lab
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/lab-实验台.md
  type: wiki
supersedes: []
tags:
- 实验平台
- 调参
- 提示词
tier: canonical
title: Lab 实验台
updated_at: '2026-11-18T07:26:22Z'
---

> 用于提示词、请求格式、阈值对比实验的调参平台，与正式链路共享图谱快照与分维阈值。

# 定义

Lab 实验台是打标能力的实验与调参平台，用来对比不同提示词版本、请求格式与阈值对准确率/覆盖/成本的影响，再把结论推进正式链路。

# 关键属性

- **显式提示词 ID**：lab 使用 `scene v3 + dim v3 + label v7`（显式 ID）；published 指针仍是 v1/v1/v1，见 [[提示词管理]] 与 [[提示词短协议原则]]。
- **格式已唯一化**：请求格式选择器被删除，`requestFormat` 从 BO/VO/前端类型/IndexedDB 批次头全部移除，见 [[四段结构 jev_noul_v1]]。
- **分维阈值面板**：对**模型门控运行完全失效**（门控抹掉分数，无法离线扫阈值），见 [[模型门控 vs 服务端阈值筛选]]。
- **输入模态**：「输入」单选（纯文本/图文）已被前端隐藏，三阶段固定 `includeMainImage=true`，见 [[图片始终发送]]。
- **一致性机制**：与正式链路、异步任务共享同一图谱快照与 `graph_dimension.label_threshold`，见 [[阈值挂图谱表]]。

# 关系

- 依赖 [[标签图谱]]、[[提示词管理]]、[[JEV 推理服务]]。
- 与 [[打标系统]] 对照运行；样本来自 [[评估样本集]]。
- 评估口径受 [[砍标签类改动的评估口径]] 约束。

# Citations

- `02-方案选型与权衡.md` §2、§8、§21
