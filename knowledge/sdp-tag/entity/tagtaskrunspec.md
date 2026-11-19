---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tagtaskrunspec
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tagtaskrunspec.md
  type: wiki
supersedes: []
tags:
- 快照
- 任务
- 一致性
tier: canonical
title: TagTaskRunSpec
updated_at: '2026-11-18T07:26:22Z'
---

> 任务受理时固化的运行规格快照（run_spec_json），决定按快照跑完、不自动重建。

# 定义

`TagTaskRunSpec` 是打标任务受理时生成的运行规格快照，序列化为 `run_spec_json`，包含图谱快照、阈值等运行参数。

# 关键属性

- **按快照跑完**：已受理任务使用自身 `run_spec_json`，不随配置变化而漂移；取消自动重建。
- **`configurationError` 也会被固化**：所以「改库配置 + 改任务状态」不会让任务成功，必须清 spec 里的 `configurationError` 并让它判 STALE 后重建。
- **`ensureTaskInTransaction` 永远用 `specFactory.create` 构建默认规格**——所以「自动重建沿用旧 `run_spec_json`」在现有实现里根本不存在。
- **三方一致性**：图谱快照随 spec 走，使 [[Lab 实验台]]、[[打标系统]]、异步任务共享同一份阈值，见 [[阈值挂图谱表]]。

# 关系

- 被 [[打标系统]] 与 [[回调服务]] 消费。
- 与 [[活动任务先到先得 + 快照执行]]、[[阈值挂图谱表]] 强相关。

# Citations

- `02-方案选型与权衡.md` §3、§19
