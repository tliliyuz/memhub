---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/docker-e982f1
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/docker.md
  type: wiki
supersedes: []
tags:
- 容器
- 运行时
- 部署
tier: canonical
title: Docker
updated_at: '2026-11-18T07:26:22Z'
---

> 主机上的容器运行时（27.5.1），承载 tdai 三件套容器；容器由 systemd 按需重建，因此运行期手工改动不持久。

# Docker

## 定义

[[腾讯云 CVM VM-0-10-ubuntu]] 上的容器运行时（版本 27.5.1），运行三个记忆栈容器：[[tdai-memory-core]]、[[tdai-memory-hub]]、[[tdai-proxy]]。

## 关键属性

- 版本：27.5.1；`docker.service` 由 systemd 管理。
- 网络：默认 bridge（docker0，网关 172.17.0.1），[[magpie gateway]] 即绑定在该地址上供容器访问。
- 卷：`tdai-memory-core-data`（320.5 MB）、`tdai-panel-data`（9.3 MB）→ [[Docker 卷数据持久化]]。
- 容器均**未设置 memory limit**（0）。

## 关系

- ← [[memhub-stack 服务单元]]：oneshot 单元负责 `docker run`/重建容器，是 [[容器化部署与重建语义]] 的核心。
- 容器端口一律带 `127.0.0.1:` 前缀（[[最小暴露面绑定原则]]）。
- 无限制容器叠加 3659 MiB 宿主机 → [[资源配额与 OOM 风险]]。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
