---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/pod
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/pod-中转镜像推送.md
  type: wiki
supersedes: []
tags:
- 镜像
- 推送
- k8s
- 排障
tier: canonical
title: Pod 中转镜像推送
updated_at: '2026-11-18T07:26:22Z'
---

> 宿主直推 ACR 不可用（代理掐断 + 实例侧带宽配额约 0.2 MB/s），改用 docker save → kubectl cp → crane push；禁用 crane append。

# Pod 中转镜像推送

## Definition

当**宿主直推 [[acr-registry]] 不可用**时，把镜像通过集群内临时 Pod [[acr-relay]] 中转推送的替代方案。

## Significance

这是被真实故障逼出来的标准做法，也是「卡在环境限制上时要直接说替代方案」的教训来源。

## 标准流程

```bash
docker build --provenance=false --sbom=false -f deploy/api/Dockerfile -t <ACR>/applesaycn/sdp-tag-api:<tag> .

docker save -o img.tar <image>
kubectl -n sdp-tag cp img.tar acr-relay:/tmp/img.tar
kubectl -n sdp-tag cp crane acr-relay:/tmp/crane
kubectl -n sdp-tag exec acr-relay -- /tmp/crane push /tmp/img.tar <tag>
kubectl -n sdp-tag delete pod acr-relay
```

## 根因的两种记录（都对，指不同现象）

| 来源 | 结论 |
| --- | --- |
| `[D]` | 宿主 `docker push` 被 Docker Desktop 代理掐断（`192.168.65.1:3128 … broken pipe`）；宿主 crane 直连 **48 KB/s** |
| `[Z]` | **不是代理问题**——切无代理同样失败；`maven.aliyun.com` 能跑 12.5 MB/s，**只有 ACR 实例慢**（~0.2 MB/s，并行不叠加，0% 丢包 10ms）。是**实例侧带宽配额** |

**合并结论**：宿主直推不可用，原因叠加；**pod 中转是正确方案**（`kubectl cp` 163MB ≈ 6.9s，pod 到 ACR ≈ 15~30s）。

## 禁令

- ⚠️ **不要用 `crane append`**——每次叠 150MB+ jar，实测 8 层 / 748 MB
- ⚠️ 构建必须带 `--provenance=false --sbom=false`
- ⚠️ Windows 下 `kubectl cp` **不能带盘符**；Git Bash 下需 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`

## 一个 4 小时的教训 `[Z]`

重试 147MB 推送多次失败后，**用户自己一分钟就推完了**。卡在环境限制上时要**直接说替代方案**。

## Related Entities

- [[acr-registry]] — 目标
- [[acr-relay]] — 中转 Pod
- [[tke-cluster-cls-62409zrl]] — 运行平台
- [[image-release-pipeline]] — 上游构建

## Common Topics

- 部署模型 / 发布流程
- 网络与代理排障

## Citations

- §2.2 镜像推送：宿主直连是坏的，走 pod 中转
