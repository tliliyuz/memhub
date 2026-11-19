---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/serverless-amqp
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/消息队列-阿里云-serverless-amqp.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 消息队列
- 可靠性
tier: canonical
title: 消息队列 / 阿里云 Serverless AMQP
updated_at: '2026-11-18T07:26:22Z'
---

> 任务分发通道，未配 DLX 时拒绝即永久丢失，consumers 数字为缓存脏数据不可作为判据。

# 定义

kind: external_system

任务分发通道，采用阿里云 Serverless AMQP。交换机 / 队列 / 死信拓扑**由部署侧创建，代码不声明**。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 死信（DLX） | ⚠️ **不配** `x-dead-letter-exchange` → 代码发 `AmqpRejectAndDontRequeueException` 并打日志「转死信」，但消息被 broker **直接丢弃**（B5 / [[消息可靠性与死信（DLX）]]） |
| `consumers` 指标 | 缓存脏数据：加一个消费者数字从 42 掉到 40，20 秒内从 2 跳到 40 → **不可用**（C9） |
| `ready=0` | 不能推断「没有流量」，要取两次采样或当「未知」（C9） |
| Management API | 本 broker 上 **15672 不通**，只有 5672；`queueDeclarePassive` 为读 `consumers` 的正解（C8/C9） |
| 端口 | 容器端口是 **8080**，不是 5672（C8 误判来源） |
| 消费容器 | 毒消息会**打死整个容器**：缺 `productName` 的消息使 Spring 重试 3 次耗尽后停消费者并重新入队，后续 1,960 条全堵死需人工恢复（D12） |

# 关系

- ↔ [[打标引擎（TagEngine）]] / [[实验台（lab）]]：批次重试与超时决定消息最终是否被 reject。
- ↔ [[对方 V2 回写系统]]：假成功导致 ACK，消息不再重投。
- ↔ [[并发与限流]]：并发抬高时上游 503 → 批次失败 → reject。
- ↔ [[静默失败]]：无 DLX 是本系统最彻底的静默丢失机制。

# 诊断纪律

- 判断「有没有人在抢队列」用**功能探针**（发几条看还在不在队列里），不要读 `consumers`，也不要从日志行或猜 socket 端口推断。
- 因 `consumers` 不信任，曾**撤回**「40 个是对方的」这一推断。

# Citations

- B3、B5、B8、C8、C9、D12、G1、G7；出处见 [[03-失败与被推翻]]。
