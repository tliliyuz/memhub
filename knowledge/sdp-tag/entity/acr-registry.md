---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/acr-registry
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/acr-registry.md
  type: wiki
supersedes: []
tags:
- 阿里云
- 镜像仓库
- 凭据风险
tier: canonical
title: acr-registry
updated_at: '2026-11-18T07:26:22Z'
---

> 阿里云 ACR 镜像仓库 applesaycn-registry.cn-shanghai.cr.aliyuncs.com/applesaycn，账号 jacky.chen@applesay.cn，口令与 RDS root 同值（P0）。

# acr-registry

## Definition

阿里云容器镜像服务（ACR）仓库，承载 sdp-tag 全部业务镜像（`sdp-tag-api` / `sdp-tag-web` / `sdp-tag-snailjob`）。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 地址 | `applesaycn-registry.cn-shanghai.cr.aliyuncs.com/applesaycn` |
| 账号 | `jacky.chen@applesay.cn` |
| 口令 | `sx@12345…` 🔴 **与 MySQL root 同值** |
| 拉取 Secret | `acr-pull`（ns `sdp-tag`） |

## Relationships

- **推送流程**：[[image-release-pipeline]]；宿主直推不通，改走 [[pod-relay-image-push]] + [[acr-relay]]
- **凭据风险**：与 [[aliyun-rds-instances]] 共用同一口令 → [[credential-leak-and-rotation]]
- **消费方**：[[tke-cluster-cls-62409zrl]]

## 已知问题

### P0：一处泄露 = 三处失守

ACR 口令与 MySQL root 口令是**同一个值**，且已在会话里以 `docker login … -p '…'` 出现多次：

- `[Z]` repo `zara-user-action-rt-agg-by-state` 的 `scripts/deploy_prod.ps1` 里就写着 ACR 账号密码

### 网络异常

- `[Z]` **ACR 有 IP 白名单波动**：`ping` 通但 TCP 443/80 被丢；同一时刻 `maven.aliyun.com` / baidu / 腾讯 443 都正常。手机热点不解决
- `[D]` 宿主 `docker push` 被 Docker Desktop 代理掐断（`192.168.65.1:3128 … broken pipe`）；宿主 crane 直连仅 **48 KB/s**
- `[Z]` 真正主因是**实例侧带宽配额**（~0.2 MB/s，并行不叠加，0% 丢包 10ms）

## Citations

- §0 P0-1
- §2 集群与部署表（ACR 行）
- §2.2 镜像推送根因两种记录
