---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-4e5ac6f0
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/部署清单漂移.md
  type: wiki
supersedes: []
tags:
- k8s
- 部署
- 事故
- 清单
tier: canonical
title: 部署清单漂移
updated_at: '2026-11-18T07:26:22Z'
---

> 两份 deploy/k8s/api.yaml（一份长期 untracked）、清单 tag 与集群实跑不一致；kubectl apply 会覆盖 set env，且清单 vhost/并发是测试口径——以集群实际状态为准。

# 部署清单漂移

## Definition

部署清单（`deploy/k8s/*.yaml`）所描述的期望状态，与 TKE 集群**实际运行状态**长期不一致的现象。

## Significance

这是**真实事故**，而且是复合型：多个独立偏差叠加后会一次性把生产切错。

## 实际情况

| 位置 | 状态 |
| --- | --- |
| `D:\workplace\sdp-tag\deploy\k8s\api.yaml` | 已 tracked（9 个文件在 git 里） |
| `D:\workplace\sdp-tag-k8s\deploy\k8s\api.yaml` | 曾长期 **untracked**，改那份永远进不了 git |

**现状**：清单 tag 与集群实际跑的**不一致**（清单 `20261030161500`，集群 `20261101184615`）。

## 两条会互相打架的坑

1. **`kubectl apply` 会用清单覆盖手工 `kubectl set env`**
2. **仓库里 `api.yaml` 的 vhost / 并发是测试口径**——随手 apply 会把流量切到 prod vhost

## 规矩

> **别信清单，以集群实际状态为准。**

先用 `kubectl get deploy ... -o yaml` 核对实跑状态，再决定是否 apply。

## Related Entities

- [[sdp-tag-api]] — 漂移主体
- [[tke-cluster-cls-62409zrl]] — 实际状态所在地
- [[image-release-pipeline]] — 可覆盖 tag + IfNotPresent 与清单 tag 不一致叠加成事故
- [[k8s-secret-injection]] — `sdp-tag-api-runtime` 未接清单
- [[gogs-sdp-tag]] — untracked 清单的历史成因

## Common Topics

- 部署模型
- 发布流程 / 事故复盘

## Citations

- §2.4 部署清单漂移（真实事故）
