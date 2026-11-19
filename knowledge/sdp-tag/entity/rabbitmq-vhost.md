---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/rabbitmq-vhost
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/rabbitmq-vhost.md
  type: wiki
supersedes: []
tags:
- RabbitMQ
- 消息队列
- 环境隔离
tier: canonical
title: rabbitmq-vhost
updated_at: '2026-11-18T07:26:22Z'
---

> 两套完全隔离的 RabbitMQ vhost（/applesay 为 test、applesay 为 prod），仅差一个前导斜杠，队列名同名不能用环境判断。

# rabbitmq-vhost

## Definition

sdp-tag 的 RabbitMQ 虚拟主机与队列配置，是打标消息的入口。

## Key Attributes

| 变量 | test | prod | 说明 / 坑 |
| --- | --- | --- | --- |
| `AUTO_TAGGING_RABBIT_VIRTUAL_HOST` | `/applesay` | `applesay` | ⚠️ **只差一个前导斜杠，是两个完全隔离的 vhost** |
| `AUTO_TAGGING_RABBIT_QUEUE` | `ai_tagging_product` | 同名 | ⚠️ **不能靠队列名判断环境** |
| `AUTO_TAGGING_RABBIT_CONCURRENCY` | 1 | 2（压测被调到 10，出事） | 只管 MQ 消费线程，**≠ 打标并行度** |
| `AUTO_TAGGING_RABBIT_TENANT_ID` | 无 | `838124` | ⚠️ 不配 → `TagMessageHandler:214` 抛异常 → NACK 不重回队列 → **5,700+ 条瞬间全烧** |
| `AUTOTAGGING_RABBIT_RUNTIMEOUT` | — | `30m` | ⚠️ **少一个下划线**；默认 10m 会把真实商品截断成部分结果 |
| `AUTO_TAGGING_RABBIT_ENABLED` | true | true | 暂停消费时**清单里也要同步改** |

## Relationships

- **环境差异**：[[environment-isolation]]
- **命名坑**：[[env-var-relaxed-binding]]（`AUTOTAGGING_RABBIT_RUNTIMEOUT`）
- **回调**：[[callback-and-brand-allowlist]]
- **本地启动必须关闭** `auto-startup` → [[local-dev-runtime-baseline]]
- **Secret**：`sdp-tag-rabbit`（ns `sdp-tag`）

## 已知问题

- ⚠️ **队列名同名，环境无法靠队列名判断**，只能靠 vhost 前导斜杠
- ⚠️ `AUTO_TAGGING_RABBIT_TENANT_ID` 缺失会导致 NACK 不重回队列，瞬间烧掉 5,700+ 条消息
- ⚠️ 本机实例若不设 `--spring.rabbitmq.listener.simple.auto-startup=false` 会**抢生产 MQ 消息**
- `AUTOTAGGING_RABBIT_RUNTIMEOUT` 少一个下划线，默认 10m 会把真实商品截断成部分结果

## Citations

- §3.2 MQ 与回调表
