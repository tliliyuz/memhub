---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/tag
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/镜像发布与不可变-tag.md
  type: wiki
supersedes: []
tags:
- 镜像
- 发布
- k8s
- tag
tier: canonical
title: 镜像发布与不可变 tag
updated_at: '2026-11-18T07:26:22Z'
---

> tag 格式 yyyyMMddHHmmss；可覆盖 tag + imagePullPolicy IfNotPresent = 重推不重拉；2026-10-28 后镜像才带 revision 标签。

# 镜像发布与不可变 tag

## Definition

sdp-tag 镜像的构建、打 tag、推送与拉取策略。

## Significance

tag 命名看似小事，但「**可覆盖 tag + `imagePullPolicy: IfNotPresent`**」是一个**致命组合**：同名 tag 重推后集群根本不会重新拉取，导致「明明推了新镜像，跑的还是旧的」。

## Key Attributes

| 项 | 值 |
| --- | --- |
| tag 格式 | `yyyyMMddHHmmss` |
| 构建命令 | `docker build --provenance=false --sbom=false -f deploy/api/Dockerfile -t <ACR>/applesaycn/sdp-tag-api:<tag> .` |
| revision 标签 | 2026-10-28 **之后**的镜像带 `org.opencontainers.image.revision=<commit>` |
| 早期镜像 | ⚠️ **没有** revision 标签，jar 里也**没有 `git.properties`** |

## 致命组合

> **可覆盖 tag + `imagePullPolicy: IfNotPresent` = 同名 tag 重推不会重新拉取**

叠加 [[deployment-manifest-drift]]（清单 tag ≠ 集群实跑 tag）就是一次事故。

## 必带构建参数

`--provenance=false --sbom=false`——否则 BuildKit 产出带 attestation 的 manifest list，`crane push` 等工具会出问题。

## Related Entities

- [[acr-registry]] — 推送目标
- [[pod-relay-image-push]] — 宿主直推不通时的替代方案
- [[acr-relay]] — 中转 Pod
- [[deployment-manifest-drift]] — 与 tag 不一致叠加成事故
- [[sdp-tag-api]]、[[sdp-tag-web]]、[[sdp-tag-snailjob]] — 镜像实体

## Common Topics

- 部署模型
- 发布流程

## Citations

- §2.2 镜像推送
- §2.3 镜像 tag 规则与一个致命组合
