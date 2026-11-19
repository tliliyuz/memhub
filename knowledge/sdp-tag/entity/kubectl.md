---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/kubectl
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/kubectl-运维通道.md
  type: wiki
supersedes: []
tags:
- 运维
- 部署
- 平台
- 能力边界
tier: canonical
title: kubectl 运维通道
updated_at: '2026-11-18T07:26:22Z'
---

> 集群操作的能力边界：get/apply/logs/rollout 正常，exec 需重试，cp 彻底不可用，且所有调用需包 4~5 次重试。

# Schema

- **kind**: platform
- **职责**：对集群执行查询与变更的唯一运维通道；其能力边界决定了部署与排障方案的可行域。

# Definition

`kubectl` 是操作集群的通道。它不是「能用 / 不能用」的二值状态，而是**按子命令分层的可用性矩阵**，并叠加了一层普遍的重试需求。

# 关键属性（能力矩阵）

| 子命令 | 可用性 |
| --- | --- |
| `get` | 可用 |
| `apply` | 可用 |
| `logs` | 可用 |
| `rollout` | 可用 |
| `exec` | **重试后可用** |
| `cp` | **彻底不可用**——连 100 KB 都 30 s 超时 |

**重试要求**：所有调用都需包 **4~5 次重试循环**，典型失败为 `TLS handshake timeout` / `Unable to connect`。SPDY 通道不稳定。

# 冲突与裁决

**A5：`exec` / `cp` 到底能不能用？**

| 说法 | 来源 |
| --- | --- |
| 「exec/cp 经常 30 秒超时（SPDY 通道被卡），但 get/apply/logs/rollout 正常」 | `[D]` |
| 「exec **重试后可用**；`cp` 才是真的不行」 | `[Z]` |

**裁决：`[Z]` 更精确。** `[D]` 把 `exec` 与 `cp` 归为同一类失败，掩盖了二者在**重试后的收敛性差异**——`exec` 可收敛，`cp` 不可收敛。

# 与部署方案的关系

`cp` 不可用直接排除了「把大文件/镜像通过 `kubectl cp` 送进 pod」的中转实现，因此 [[ACR 镜像仓库]] 的 pod 中转必须走其他传输路径（在 pod 内拉取/推送镜像，而非从宿主拷贝）。

# Relationships

- [[ACR 镜像仓库]] — 部署链路的两端；`cp` 不可用改变了中转方案的实现形态。
- 排障：`logs` / `rollout` 可用意味着滚动发布与日志观测链路本身是通的。

# Citations

- 源：`06-未决与空白.md` A5
