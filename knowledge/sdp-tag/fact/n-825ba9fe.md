---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-825ba9fe
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/可观测性探针.md
  type: wiki
supersedes: []
tags:
- 可观测性
- 探针
- MQ
tier: canonical
title: 可观测性探针
updated_at: '2026-11-18T07:26:22Z'
---

> 指标不可信时改用功能探针（故意发非法消息看 20s 内是否打预期警告）；/proc/net/tcp 端口换算（5672=0x1628）是唯一硬信号。

# Definition

当现成指标不可信（脏数据、API 不通）时，用**主动制造可观测事件**来判定链路状态的手段。

# 核心手段

1. **功能探针（MQ）**：发一条**故意非法**的消息，看 20 秒内是否被消费并打出预期警告。

   ```
   发一条 brand 为空的消息 → 日志出现「打标消息无法处理，转死信：brand 不能为空」= 消费链路通
   ```

2. **连接硬信号**：`/proc/net/tcp` 里有到 broker 5672 的连接。端口换算 **5672 = 0x1628**（曾 grep `:1626`，而 `0x1626 = 5670`，判断错误；容器端口是 8080）。

# Significance

- 阿里云 Serverless AMQP 的 `consumers` 是**脏数据**（42→40、2→40 抖动），`ready=0` 不能推断「没有流量」，15672 management API 又**不通**（只有 5672）→ 只能靠探针。见 [[aliyun-serverless-amqp]]。
- 队列名与 vhost 也不能当环境判别信号，见 [[环境隔离与串环境事故]]。
- 通用原则：**可观测性缺口要用主动实验填，不要用可疑指标推断**。

# Related entities

[[aliyun-serverless-amqp]] · [[sdp-tag-api]] · [[tag_mq_rejected]]

# Common topics

- **可观测性**：指标可信度分级（硬信号 / 派生指标 / 脏数据）。
- **运维流程**：消费容器停止后需人工恢复，探针是恢复前的验证。

# Citations

- 04 排障信号手册 §1.5、§2.2、§2.4
