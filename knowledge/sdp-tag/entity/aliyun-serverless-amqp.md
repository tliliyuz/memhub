---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/aliyun-serverless-amqp
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/aliyun-serverless-amqp.md
  type: wiki
supersedes: []
tags:
- MQ
- 中间件
- 外部系统
- 脏指标
tier: canonical
title: aliyun-serverless-amqp
updated_at: '2026-11-18T07:26:22Z'
---

> 阿里云 Serverless AMQP 消息中间件，consumers 指标不可信、15672 management API 不通（只有 5672），vhost 与队列名存在环境陷阱。

# Definition

上游消息中间件，[[sdp-tag-api]] 通过它接收打标消息。它的观测面**不可信**，是「看指标会走错路」的典型案例。

# Key attributes

## 不可信的指标

- **`consumers` 是脏数据**：实测加一个消费者数字从 42 掉到 40；同一条队列 20 秒内从 2 跳到 40。
- **`ready=0` + N 个消费者不能推断「没有流量」**：取两次采样当作「未知」。
- **15672 management API 不通，只有 5672**（拿不到速率指标）→ 改用[[可观测性探针]]。

## 端口与连接判定

- 唯一硬信号：`/proc/net/tcp` 里有到 broker 5672 的连接。端口换算 **5672 = 0x1628**（曾 grep `:1626` = 5670 判断错误；容器端口是 8080，不是 5672）。

## vhost 与队列名

| 环境 | vhost |
| --- | --- |
| test | `/applesay` |
| prod | `applesay`（**无前导斜杠**） |

- 只差一个斜杠：这是把 2,025 条测试结果写进对方生产库的直接原因，见 [[环境隔离与串环境事故]]。
- **队列名不能辨环境**：两环境都叫 `ai_tagging_product`。

## 四种「没被消费」的故障区分

| 现象 | 结论 |
| --- | --- |
| `consumers = 0` | 我们这边根本没连上 broker |
| `consumers ≠ 0` 但没消费 | 发错交换机 / 路由键 |
| 发到默认交换机且无路由 | **静默丢弃**，日志里什么都没有 |
| 刚切完 vhost | broker 计数滞后，等一分钟再看 |

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[sdp-tag-api]] | 消费端（4 线程 / 200 队列 / AbortPolicy） |
| [[tag_mq_rejected]] | 拒收留痕与人工重放 |
| [[可观测性探针]] | 指标不可信时的替代判定手段 |
| [[环境隔离与串环境事故]] | vhost 斜杠与同名队列 |

# Citations

- 04 排障信号手册 §2.2、§2.3、§2.4、§2.5
