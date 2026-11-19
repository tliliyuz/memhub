---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/decathlon-data-extractions
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/decathlon-data-extractions.md
  type: wiki
supersedes: []
tags:
- k8s
- 既有资源
- 禁止触碰
tier: canonical
title: decathlon-data-extractions
updated_at: '2026-11-18T07:26:22Z'
---

> 已占用 sdp-api/sdp-web.applesay.cn（ingress decathlon-api）的既有业务，不可复用或编辑。

# decathlon-data-extractions

## Definition

TKE 集群上已有的另一套业务，**已占用 `sdp-api.applesay.cn` 与 `sdp-web.applesay.cn` 域名**（ingress 名 `decathlon-api`）。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 占用域名 | `sdp-api.applesay.cn`、`sdp-web.applesay.cn` |
| Ingress 名 | `decathlon-api` |
| 归属 | 非 sdp-tag 团队 |

## Relationships

- **所在集群**：[[tke-cluster-cls-62409zrl]]
- **冲突对象**：[[sdp-tag-api]] / [[sdp-tag-web]] 的域名规划

## 已知问题

⚠️ **`[Z]` 明确列为不可触碰**：不要复用或编辑该 ingress 与域名。sdp-tag 只能使用 `sdp-tag-web.applesay.cn` / `sdp-tag-api` 自己的域名。

## Citations

- §2.1 不可触碰的既有资源
