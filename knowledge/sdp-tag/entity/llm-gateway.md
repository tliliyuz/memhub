---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/llm-gateway
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/llm-gateway.md
  type: wiki
supersedes: []
tags:
- 模型
- 外部系统
- 限流
tier: canonical
title: llm-gateway
updated_at: '2026-11-18T07:26:22Z'
---

> LLM 模型调用网关，503 多为渠道熔断而非模型下线，限流按「用户」而非 key 计（统一 100 并发）。

# Definition

模型调用入口。打标链路所有判分/打标模型请求都经过它，是「模型 503」类问题的现场。

# Key attributes

## 判别顺序（别急着换模型）

1. 用同一把 key、同一个模型**单独打一次网关**
2. `GET /v1/models` 看模型是否在列表里
3. 都正常 → **不是模型下线**，是并发/渠道问题

| 错误 | 含义 |
| --- | --- |
| `503 model_not_found No available channel for model … under group project` | **渠道熔断 / 冷却**，不是模型下线 |
| `429 maximum 100 requests in 1 minutes` | key 限流 |

## 限流口径

> 「配额不按 key 分，按照用户分，所以不管我给你们多少 key，你们都只有 100 并发。」

→ **加 key 不解决限流。**

## 并发经验值

qwen 下：并发 24 → 180s 超时；20 → `HttpConnectTimeout`；12 仍级联；**8 + 一次网络重试全部完成**。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[sdp-tag-api]] | 打标链路的调用方 |
| [[chat-judge-model]] | 评测台的 chat judge 实现（输出 token 驱动的慢） |
| [[chat 源 vs systemone 源（judge 对比）]] | 两个 judge 源的稳定性差异 |

# Citations

- 04 排障信号手册 §4.4
