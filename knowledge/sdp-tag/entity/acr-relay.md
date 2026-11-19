---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/acr-relay
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/acr-relay.md
  type: wiki
supersedes: []
tags:
- k8s
- 镜像推送
- 中转
tier: canonical
title: acr-relay
updated_at: '2026-11-18T07:26:22Z'
---

> 临时中转 Pod，用于 kubectl cp + crane push 绕过宿主直推 ACR 的带宽/代理故障。

# acr-relay

## Definition

在 `sdp-tag` 命名空间临时创建的 Pod，作为推送镜像到 [[acr-registry]] 的中转站。

## 使用流程

```bash
docker save -o img.tar <image>
kubectl -n sdp-tag cp img.tar acr-relay:/tmp/img.tar
kubectl -n sdp-tag cp crane acr-relay:/tmp/crane
kubectl -n sdp-tag exec acr-relay -- /tmp/crane push /tmp/img.tar <tag>
kubectl -n sdp-tag delete pod acr-relay
```

## Key Attributes

| 项 | 值 |
| --- | --- |
| 所在命名空间 | `sdp-tag` |
| 生命周期 | **临时**，用完即 `delete pod` |
| 实测性能 | `kubectl cp` 163MB ≈ 6.9s；pod → ACR ≈ 15~30s |

## Relationships

- **目标仓库**：[[acr-registry]]
- **所属概念**：[[pod-relay-image-push]]
- **部署平台**：[[tke-cluster-cls-62409zrl]]
- **前置产物**：[[image-release-pipeline]] 打好的镜像 tar

## 已知问题

- ⚠️ **不要用 `crane append`**——每次叠 150MB+ jar，实测 8 层 / 748 MB
- ⚠️ Windows 下 `kubectl cp` **不能带盘符**；Git Bash 下需处理路径转换

## Citations

- §2.2 镜像推送：宿主直连是坏的，走 pod 中转
