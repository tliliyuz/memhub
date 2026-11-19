---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/cvm-vm-0-10-ubuntu
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/腾讯云-cvm-vm-0-10-ubuntu.md
  type: wiki
supersedes: []
tags:
- 基础设施
- 云主机
- 腾讯云
tier: canonical
title: 腾讯云 CVM VM-0-10-ubuntu
updated_at: '2026-11-18T07:26:22Z'
---

> 承载 memhub 记忆栈全部服务的单台腾讯云云服务器（4 vCPU / 3659 MiB / 40 GiB），是本知识库所有服务实体的宿主。

# 腾讯云 CVM VM-0-10-ubuntu

## 定义

单台腾讯云 CVM（Cloud Virtual Machine）实例，主机名 `VM-0-10-ubuntu`，承载 [[memhub.work 域名]] 背后的全部服务：[[nginx]]、[[tdai-memory-hub]]、[[tdai-memory-core]]、[[tdai-proxy]]、[[magpie gateway]]。目前是**唯一的**宿主机，无集群、无冗余。

## 关键属性

| 项目 | 值 |
|---|---|
| 公网 IP | 43.142.18.23 |
| 内网 IP | 10.0.0.10 |
| 操作系统 | Ubuntu 24.04 LTS |
| 内核 | 6.8.0-49-generic |
| 架构 | x86_64 |
| CPU | AMD EPYC 7K62 48-Core，4 vCPU（1 socket × 4 core × 1 thread） |
| 内存 | 3659 MiB |
| Swap | 1987 MiB（`/swap.img`） |
| 系统盘 | 40 GiB ext4，已用 9.2 GiB（25%），可用 29 GiB |
| 运行时 | [[Docker]] 27.5.1 |

快照时刻资源：已用 1539 MiB / 可用 2119 MiB / buff/cache 2162 MiB / Swap 使用 0 / 负载 0.08、0.04、0.05。

## 关系

- **hosted-on 反向**：本机承载上述全部服务实体与三个 Docker 卷。
- [[腾讯云安全组]] 是本机事实上的入站边界防火墙（ufw 未启用）。
- [[systemd-resolved]] 提供本机 DNS 解析（127.0.0.53 / 127.0.0.54）。
- 容量约束（内存仅 3659 MiB 且容器无 limit）直接构成 [[资源配额与 OOM 风险]]。
- 运维操作见 [[运维操作手册]]；容器由 [[memhub-stack 服务单元]] 拉起。

## 已知限制

- 单机部署：既是入口、又是计算与存储节点，无高可用。
- 内存与系统盘容量小，无法容纳大规模本地模型或大量数据副本。
- 快照中系统盘已用仅 25%，主要增长点在 [[Docker 卷数据持久化]] 中的两个数据卷。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
