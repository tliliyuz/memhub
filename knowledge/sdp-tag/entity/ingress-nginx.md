---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/ingress-nginx
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/ingress-nginx.md
  type: wiki
supersedes: []
tags:
- 平台
- 网关
- 超时
tier: canonical
title: ingress-nginx
updated_at: '2026-11-18T07:26:22Z'
---

> 集群入口，proxy-read-timeout 默认 60s，是端到端 504 的第一层天花板；超时表现为应用日志无请求 + web nginx 记 499。

# Definition

Kubernetes 入口层，把外部请求转给 [[sdp-tag-web]]。它构成端到端超时链路中**最短**的那块天花板。

# Key attributes

| 项 | 值 |
| --- | --- |
| 关键参数 | `proxy-read-timeout` |
| 默认 | **60s**（已改 600） |
| 配置位置 | `deploy/k8s/ingress.yaml` 注解 |
| 判别信号 | 应用日志里**根本没有这次请求** + web 的 nginx 记 `499` |

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[分层超时]] | 两层天花板的归属概念页：**必须两层一起抬，短的赢** |
| [[sdp-tag-web]] | 下层 300s 天花板 |

# Citations

- 04 排障信号手册 §4.9
