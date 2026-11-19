---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/tdai-memory-hub
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/tdai-memory-hub.md
  type: wiki
supersedes: []
tags:
- 容器
- 记忆栈
- 服务
tier: canonical
title: tdai-memory-hub
updated_at: '2026-11-18T07:26:22Z'
---

> 记忆中枢容器（镜像 agentmemory/memory-hub），提供面板（8125）与 knowledge（8424）两个回环监听面，向下调用 tdai-memory-core。

# tdai-memory-hub

## 定义

memhub 记忆栈的中枢服务，镜像 `agentmemory/memory-hub:latest`，由 [[memhub-stack 服务单元]] 在 core 之后拉起。对外通过 [[nginx]] 反向代理暴露面板，对内依赖 [[tdai-memory-core]]。

## 关键属性

| 项目 | 值 |
|---|---|
| 镜像 | `agentmemory/memory-hub:latest` |
| 面板端口 | 8125（127.0.0.1，经 nginx 反代） |
| knowledge 端口 | 8424（127.0.0.1） |
| 实际内存 | 103.7 MiB（2.8%） |
| CPU | 0.02% |
| memory limit | 未限制（0），建议 512m |
| 数据卷 | `tdai-panel-data`（9.3 MB，面板配置 + knowledge 数据） |

## 关系

- ↔ [[tdai-memory-core]]：同栈上下游依赖（hub 调 core）。
- ← [[nginx]]：面板被反代到 443。
- ← [[memhub-stack 服务单元]]：按 `core → hub → proxy` 顺序拉起，容器会被重建。
- 数据持久化见 [[Docker 卷数据持久化]]；内存风险见 [[资源配额与 OOM 风险]]。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
