---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/dlx
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/消息可靠性与死信-dlx.md
  type: wiki
supersedes: []
tags:
- 可靠性
- 消息队列
- 运维
tier: canonical
title: 消息可靠性与死信（DLX）
updated_at: '2026-11-18T07:26:22Z'
---

> 无 DLX 时拒绝即永久丢失，毒消息可打死整个消费容器，无 graceful shutdown 会截断在途任务。

# 定义

消息可靠性指任务消息从入队到被成功处理之间的保障机制，核心构件包括死信交换机（DLX）、重试策略、毒消息隔离、优雅停机（graceful shutdown / `preStop`）。本页讲**机制**；跨领域的失败模式见 [[静默失败]]；缺口状态见 [[已知未修缺口清单]]。

# 重要性

在本系统中，「拒绝」与「丢失」是同义词：代码只发 `AmqpRejectAndDontRequeueException` 并打日志「转死信」，但**交换机/队列/死信拓扑由部署侧创建，代码不声明**。队列未配 `x-dead-letter-exchange` 时 broker 直接丢弃消息，此刻日志仍在说「转死信」。

# Schema：机制与后果

| 机制点 | 当前状态 | 后果 |
| --- | --- | --- |
| DLX | ⚠️ **仍不配** | 57 条真实商品消息永久丢失，不回灌、不重放（B3/B5） |
| 批次重试 | 正式链路 2 次，实验链路 `maxBatchRetries=0` | 一次 429 整件重来（B7） |
| 毒消息 | 缺 `productName` → Spring 重试 3 次耗尽 → 停消费者 + 重新入队 | 后续 **1,960 条**堵死，需人工恢复（D12） |
| 缺 `tenantId` | `TagMessageHandler:214` 抛异常 → NACK 不重回队列 | **5,700+ 条**瞬间全烧（D12） |
| `TagMqRejectionRecorder` | `@Transactional` | 把「拒绝跳过」变成「停消费者」（G3） |
| 优雅停机 | ⚠️ 无 graceful shutdown / `preStop`（G7） | 滚动更新时在途任务被截断 |
| 超时语义 | `run-timeout` 到点只停止派发、照常回调 | 「部分结果」被当成功（B9/G2） |
| 超时误用 | `run-timeout=5s` 用于验证绑定 | 阶段失败 → reject → 进死信 → 根本不会发起回调（B8） |

# 观测与诊断

- **不要用 `consumers` 数字**：阿里云 Serverless AMQP 的缓存脏数据（加消费者 42→40，20 秒内 2→40）。
- **用功能探针**：发几条消息，看还在不在队列里。
- `queueDeclarePassive` 是读 `consumers` 的正解；容器端口是 **8080** 而非 5672；该 broker 15672 不通、只有 5672。
- `ready=0` 且 N 个消费者时**不能推断「没有流量」**，要取两次采样或视为未知。

# 相关实体

- [[消息队列 / 阿里云 Serverless AMQP]]、[[打标引擎（TagEngine）]]、[[对方 V2 回写系统]]

# Citations

- B3、B5、B7、B8、B9、C8、C9、D12、G1、G2、G3、G7；出处见 [[03-失败与被推翻]]。
