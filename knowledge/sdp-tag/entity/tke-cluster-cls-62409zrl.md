---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tke-cluster-cls-62409zrl
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tke-cluster-cls-62409zrl.md
  type: wiki
supersedes: []
tags:
- 腾讯云
- TKE
- k8s
- 集群
tier: canonical
title: tke-cluster-cls-62409zrl
updated_at: '2026-11-18T07:26:22Z'
---

> 腾讯云上海 TKE 集群（6 节点，K8s v1.34.1-tke.1），命名空间 sdp-tag，API 为 k8s-tencent.applesay.cn:443。

# tke-cluster-cls-62409zrl

## Definition

sdp-tag 全部服务所在的腾讯云 TKE 集群（上海地域），命名空间 `sdp-tag`。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 集群 ID | `cls-62409zrl` |
| API 端点 | `k8s-tencent.applesay.cn:443`（43.140.73.159） |
| K8s 版本 | `v1.34.1-tke.1` |
| 节点数 | 6 |
| 命名空间 | `sdp-tag` |
| kubeconfig | `C:\Users\Applesay024\Downloads\cls-62409zrl-config` |

### Secret 清单（ns `sdp-tag`）

| Secret | 用途 | 状态 |
| --- | --- | --- |
| `acr-pull` | 镜像拉取凭据 | 在用 |
| `sdp-tag-rabbit` | MQ 连接 | 在用 |
| `sdp-tag-db` | 数据库口令 | 在用 |
| `sdp-tag-callback` | 回调 `AUTH_VALUE` | 在用 |
| `sdp-tag-api-runtime` | 运行时配置 | ⚠️ **只在 `deploy/README.md` 里存在，清单没接** |

## Relationships

- **承载服务**：[[sdp-tag-api]]、[[sdp-tag-web]]、[[sdp-tag-snailjob]]、[[acr-relay]]
- **镜像来源**：[[acr-registry]]
- **权限主体**：[[ops-subaccount-cluster-admin]]（实质 cluster-admin）
- **配置注入**：[[k8s-secret-injection]]
- **清单状态**：[[deployment-manifest-drift]]

## 不可触碰的既有资源 `[Z]`

| 资源 | 原因 |
| --- | --- |
| `sdp-api.applesay.cn` / `sdp-web.applesay.cn` | **已属于 [[decathlon-data-extractions]]**（ingress `decathlon-api`），不可复用或编辑 |
| `kubernetes-proxy`（default ns） | TKE 自己的 API 代理 |
| `mongodb` / `unifi` 等既有 Deployment | 不是我们的 |
| `agents` ns 里 76 个 Deployment | 大量 0 副本，不是我们的 |

## 运维坑

- ⚠️ **默认 `~/.kube/config` 里没有该集群**，每条 kubectl 都要带 `--kubeconfig`
- ⚠️ `kubectl cp` 连 100KB 都 30s 超时（SPDY 流被卡）；`exec` 重试后可用
- ⚠️ `kubectl` 本身间歇 `TLS handshake timeout` / `Unable to connect`，**要包 4~5 次重试循环**
- ⚠️ Windows 下 `kubectl cp` **不能带盘符**，`D:\...` 的冒号被当成 `pod:路径`
- ⚠️ Git Bash 下需 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`，否则 `/busybox/x` 被改写

## Citations

- §2 集群与部署表
- §2.1 不可触碰的既有资源
- §9 绝不能进仓库的清单（kubeconfig 行）
