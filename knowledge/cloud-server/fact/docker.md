---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/docker
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/docker-卷数据持久化.md
  type: wiki
supersedes: []
tags:
- 数据持久化
- 备份
- Docker
tier: canonical
title: Docker 卷数据持久化
updated_at: '2026-11-18T07:26:22Z'
---

> 业务数据全部落在两个 Docker 卷（tdai-memory-core-data 320.5 MB、tdai-panel-data 9.3 MB），跨容器重建保留，但目前无自动备份。

# Docker 卷数据持久化

## 定义

在 [[容器化部署与重建语义]] 下容器本身是一次性的，唯一跨重建存活的是 Docker 卷。当前有两个业务卷：

| 卷 | 大小 | 内容 | 归属 |
|---|---|---|---|
| `tdai-memory-core-data` | 320.5 MB | L0/L1 记忆层、skills、meta 库（SQLite） | [[tdai-memory-core]] |
| `tdai-panel-data` | 9.3 MB | 面板配置、knowledge 数据 | [[tdai-memory-hub]] |

## 意义

- 界定了"可重建"与"不可重建"的边界：镜像与容器可随时重建，卷内不可再生。
- **缺口**：无自动备份策略，仅依赖手工快照。丢失卷等于丢失全部记忆资产，而主机系统盘尚有 29 GiB 可用、备份成本很低。
- 与 [[资源配额与 OOM 风险]] 相交：SQLite meta 库在 OOM 或强杀瞬间存在损坏风险，备份同时是完整性保障。

## 相关实体

[[tdai-memory-core]]、[[tdai-memory-hub]]、[[Docker]]、[[memhub-stack 服务单元]]

## 常见话题

部署模型、数据流、可靠性

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
