---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/system-one-typesafe
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/system-one-typesafe.md
  type: wiki
supersedes: []
tags:
- LLM
- 判分
- 代理
tier: canonical
title: system-one-typesafe
updated_at: '2026-11-18T07:26:22Z'
---

> Typesafe System One 判分终点 https://api.typesafe.ai/v1，模型 jev-1.13.0，必须走代理，直连 451。

# system-one-typesafe

## Definition

Typesafe（System One）判分服务，作为 `llm.judge.provider=typesafe` 时的 LLM 终点。

## Key Attributes

| 项 | 值 |
| --- | --- |
| base-url | `https://api.typesafe.ai/v1` |
| 模型 | `jev-1.13.0` |
| 网络策略 | ⚠️ **必须走代理**，直连返回 451 |
| judge provider 键 | `typesafe` |

## Relationships

- **代理策略**：走 `127.0.0.1:7897` → [[proxy-routing-policy]]（与 [[llm-gateway-applesay]] 相反）
- **平行终点**：[[ark-volces]]
- **调用方**：[[sdp-tag-backend]]（`llm.judge.provider`）

## 已知问题

- ⚠️ **与打标网关策略相反**——这是最容易搞错的一条：网关直连、Typesafe 走代理
- JVM 不读 `HTTP_PROXY` 环境变量 → 必须用 `-Dhttps.proxyHost` 系统属性，且**置于 `-jar` 之前**

## Citations

- §5 LLM 网关与 key（System One 行）
- §6 代理与网络
