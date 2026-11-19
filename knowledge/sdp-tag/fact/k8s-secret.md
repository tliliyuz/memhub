---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/k8s-secret
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/k8s-secret-注入.md
  type: wiki
supersedes: []
tags:
- k8s
- Secret
- 配置注入
tier: canonical
title: K8s Secret 注入
updated_at: '2026-11-18T07:26:22Z'
---

> Secret 以只读方式挂载到 /sdptag/server/config/application-private.yml 或注入环境变量；环境变量只在启动时读取，改完必须 rollout restart。

# K8s Secret 注入

## Definition

K8s Secret 向 Pod 注入配置的两种方式：

1. **只读文件挂载**到 `/sdptag/server/config/application-private.yml`
2. **注入为环境变量**

## Significance

这是生产凭据的唯一正确来源，也是 [[credential-leak-and-rotation]] 落地的最后一环。但它有两个陷阱，让「改了 Secret 却没生效」成为常见故障。

## 关键约束

| 约束 | 说明 |
| --- | --- |
| 环境变量**只在 Pod 启动时读取** | 改完 Secret **必须 `rollout restart`** |
| 挂载文件优先级 | 按 [[config-layering]]，`private.yml` 优先级**低于** `application.yml` |
| `optional:` 前缀 | 文件不存在时**静默跳过**，不会报错 |

## 现有 Secret（ns `sdp-tag`）

| Secret | 用途 | 状态 |
| --- | --- | --- |
| `acr-pull` | 镜像拉取 | 在用 |
| `sdp-tag-rabbit` | MQ 连接 | 在用 |
| `sdp-tag-db` | 数据库口令 | 在用 |
| `sdp-tag-callback` | 回调 `AUTH_VALUE` | 在用，改完须 restart |
| `sdp-tag-api-runtime` | 运行时配置 | ⚠️ **只在 `deploy/README.md` 里存在，清单没接** |

⚠️ `sdp-tag-api-runtime` 未接入清单 → **用仓库清单重建会回到 dev 行为**。

## Related Entities

- [[tke-cluster-cls-62409zrl]] — Secret 所在集群
- [[sdp-tag-api]]、[[sdp-tag-backend]] — 消费方
- [[config-layering]] — 挂载文件的层级位置
- [[credential-leak-and-rotation]] — 轮换后必须同步 Secret + restart
- [[deployment-manifest-drift]] — 清单没接 Secret 的后果

## Common Topics

- 部署模型 / 权限模型
- 配置体系

## Citations

- §1 配置文件位置（容器内行）
- §2 集群与部署表（Secret 行）
- §3.2 回调 AUTH_VALUE 行
