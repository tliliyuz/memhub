---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tag-mq-rejected
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tag-mq-rejected.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 数据表
- MQ
tier: canonical
title: tag_mq_rejected
updated_at: '2026-11-18T07:26:22Z'
---

> MQ 拒收留痕表（pending/replayed/ignored），配套 GET /tag/mq/rejected/list 与 POST /{id}/replay 人工重放。

# Definition

MQ 拒收消息的留痕表：消息没能进入正常处理流程时记录一行，并提供人工重放入口。

# Key attributes

| 项 | 值 |
| --- | --- |
| 状态 | `pending` / `replayed` / `ignored` |
| 错误信息 | `last_error` |
| 查询接口 | `GET /tag/mq/rejected/list` |
| 重放接口 | `POST /{id}/replay` |
| 相关指标 | `sdptag_mq_rejected_total{reason}`、`sdptag_mq_queue_depth{queue}` |

- `queue_depth` 由定时被动声明发布，**连续 5 次超 5000 才 WARN**（单次尖峰不报）。
- 监控组件 `TagMqQueueMonitor` 仅在 `auto-tagging.rabbit.enabled=true` 时生效。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[sdp-tag-api]] | 留痕写入方与重放接口提供方 |
| [[aliyun-serverless-amqp]] | 上游 broker；其 `consumers` 指标不可信，需配合[[可观测性探针]] |
| [[静默失败]] | 无路由键投递会**静默丢弃**，连留痕都没有 |

# Citations

- 04 排障信号手册 §2.5
