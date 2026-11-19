---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/ops-subaccount-cluster-admin
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/ops-subaccount-cluster-admin.md
  type: wiki
supersedes: []
tags:
- 权限
- 腾讯云
- cluster-admin
- 凭据风险
tier: canonical
title: ops-subaccount-cluster-admin
updated_at: '2026-11-18T07:26:22Z'
---

> 腾讯云子账号 100047678655，groups 含 cluster:cls-62409zrl，auth can-i '*' '*' = yes，实质集群管理员；kubeconfig 落在 Downloads。

# ops-subaccount-cluster-admin

## Definition

用于运维 sdp-tag 的腾讯云子账号，对 TKE 集群拥有**实质 cluster-admin 权限**。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 子账号 ID | `100047678655` |
| Groups | `tenant:1326693272 cluster:cls-62409zrl` |
| 权限验证 | `auth can-i '*' '*'` = **yes** |
| kubeconfig 位置 | `C:\Users\Applesay024\Downloads\cls-62409zrl-config` |

## Relationships

- **作用域**：[[tke-cluster-cls-62409zrl]]
- **可操作对象**：全部 Secret（[[k8s-secret-injection]]）
- **凭据风险**：[[credential-leak-and-rotation]]

## 已知问题

- 🟠 **kubeconfig 落在 `Downloads` 目录**，且是 **cluster-admin 级**——一旦被读取即完全失守
- 正确做法：移到 `~/.kube/` 或凭据管理器（§9）
- ⚠️ 默认 `~/.kube/config` 里没有该集群，每条 kubectl 都要带 `--kubeconfig`

## Citations

- §2 集群与部署表（身份行）
- §9 绝不能进仓库的清单（kubeconfig 行）
- §10 凭据风险汇总（🟠 高）
