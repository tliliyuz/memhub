---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tag-task
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tag-task.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 数据表
- 任务状态
tier: canonical
title: tag_task
updated_at: '2026-11-18T07:26:22Z'
---

> 打标任务状态真相源表，记录 task_status、attempt_count、lease_expire_time、run_spec_json 与 tagged_input_hash。

# Definition

打标任务的**状态真相源**表。排障时「任务卡住」按序看的第一现场，租约过期计次与终态失败都在这里累积。

# Key attributes

| 列 | 含义 / 判据 |
| --- | --- |
| `task_status` | 与 `tag_event.status` 一起看分布 |
| `attempt_count` | 到 **4** 即「任务执行次数已达上限，过期租约不再重试」→ [[租约与重试上限]] |
| `lease_expire_time` | 租约 3 分钟；与 `started_at` 对比可区分「卡死」与「慢」 |
| `started_at` | 租约仍在续但 `started_at` 很久以前 = 卡在单次模型调用上 |
| `run_spec_json.configurationError` | **worker 只读快照，改配置救不了已建任务** |
| `tagged_input_hash` | 存量全 NULL → 所有历史商品显示「结果已过期」 |
| `stale` reason | `content_changed` / `config_changed` / `input_changed` / `input_snapshot_missing` |

## 排障顺序（§3.3）

1. `tag_task.task_status` + `tag_event.status` 分布
2. `attempt_count` + `lease_expire_time` + `started_at`
3. `run_spec_json` 里的 `configurationError`
4. `stale` reason
5. `tagged_input_hash` 是否为空
6. 锁：`innodb_trx` 持锁行数 + `LOCK WAIT` 的 SQL + 线程栈

## 列名/关联表陷阱

- 事件状态在 `tag_event.status`（**不是** `event_status`）。
- 字段编码在 `tag_field_config.field_code`（**不是** `field_key`）；该表**没有 `ON UPDATE CURRENT_TIMESTAMP`**，改配置后 `update_time` 不动。
- 每阶段 `elapsedMs` / token 存在 `tag_task_evidence.evidence_gzip`，日志丢失时用它取证。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[sdp-tag-api]] | 任务的生产者与执行者 |
| [[打标四阶段链路]] | 阶段状态（`scene=completed,label=skipped`）定位归属 |
| [[租约与重试上限]] | `attempt_count` / `lease_expire_time` 的机制来源 |
| [[tag_callback_delivery]] | 终态 failed 的任务永远不会有对应投递行 |

# Citations

- 04 排障信号手册 §3.3、§6
