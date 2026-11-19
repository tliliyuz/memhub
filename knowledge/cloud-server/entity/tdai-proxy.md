---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/tdai-proxy
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/tdai-proxy.md
  type: wiki
supersedes: []
tags:
- 容器
- 记忆栈
- 接入层
tier: canonical
title: tdai-proxy
updated_at: '2026-11-18T07:26:22Z'
---

> 面向 Claude Code / Agent 的记忆注入代理容器，监听回环 8096，外部客户端目前依赖 SSH 隧道访问。

# tdai-proxy

## 定义

记忆注入代理，镜像 `agentmemory/memory-proxy:latest`，监听 `127.0.0.1:8096`。作用是在 [[Claude Code 与 Agent 客户端]] 的请求链路上注入/回写记忆，并把模型调用转交给 [[magpie gateway]]。

## 关键属性

| 项目 | 值 |
|---|---|
| 镜像 | `agentmemory/memory-proxy:latest` |
| 端口 | 8096（127.0.0.1，不公网可达） |
| 实际内存 | 87.9 MiB（2.4%） |
| CPU | 0.2% |
| memory limit | 未限制（0），建议 512m |

## 关系

- ← [[Claude Code 与 Agent 客户端]]：调用方，目前经 SSH 隧道访问 8096。
- → [[magpie gateway]]（172.17.0.1:3425）→ [[上游模型供应商]]：模型路由链路。
- ← [[memhub-stack 服务单元]]：按 `core → hub → proxy` 顺序最后拉起。
- 待办：为 8096 增加独立子域名 + 反代鉴权，摆脱 SSH 隧道依赖（须经 [[nginx]]）。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
