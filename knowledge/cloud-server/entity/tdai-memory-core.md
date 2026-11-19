---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/tdai-memory-core
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/tdai-memory-core.md
  type: wiki
supersedes: []
tags:
- 容器
- 记忆栈
- 服务
tier: canonical
title: tdai-memory-core
updated_at: '2026-11-18T07:26:22Z'
---

> 记忆核心服务容器（agentmemory/memory-core），监听 8420，是栈内资源占用最大、OOM 风险最高的组件。

# tdai-memory-core

## 定义

记忆栈的核心存储与检索服务，镜像 `agentmemory/memory-core:latest`，监听 127.0.0.1:8420，由 [[tdai-memory-hub]] 调用。

## 关键属性

| 项目 | 值 |
|---|---|
| 镜像 | `agentmemory/memory-core:latest` |
| 端口 | 8420（127.0.0.1） |
| 实际内存 | 646.7 MiB（17.7%），栈内最大 |
| CPU | 2.1% |
| memory limit | 未限制（0），建议 1536m |
| 数据卷 | `tdai-memory-core-data`（320.5 MB：L0/L1、skills、meta 库 SQLite） |

## 关系

- ← [[tdai-memory-hub]]：被 hub 调用。
- ← [[memhub-stack 服务单元]]：是三件套中**第一个**被拉起的容器。
- 数据卷是唯一的业务数据落地处，见 [[Docker 卷数据持久化]]（当前无自动备份）。
- 是 [[资源配额与 OOM 风险]] 的主要来源：单容器 646.7 MiB / 主机 3659 MiB 且无 limit。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
