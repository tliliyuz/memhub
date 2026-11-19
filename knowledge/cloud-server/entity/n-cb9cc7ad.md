---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloud-server/entity/n-cb9cc7ad
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/上游模型供应商.md
  type: wiki
supersedes: []
tags:
- 外部依赖
- 模型
- 出站
tier: canonical
title: 上游模型供应商
updated_at: '2026-11-18T07:26:22Z'
---

> magpie gateway 下游依赖的外部大模型服务提供方，本文未具名，仅确定经 gateway 出站访问。

# 上游模型供应商

## 定义

由 [[magpie gateway]] 路由到达的外部大模型服务（供应商名称在源文档中未具名）。

## 关键属性

- 访问路径：容器内 [[tdai-proxy]] → `172.17.0.1:3425`（[[magpie gateway]]）→ 上游客商 API。
- 凭据：由 magpie 的 `/root/.config/magpie/settings.json`（含 `lanKey`）统一管理，容器不直接持有上游密钥。
- 出站流量不在 [[最小暴露面绑定原则]] 讨论范围内（原则约束的是入站监听面）。

## 关系

- 是 [[记忆栈服务拓扑]] 中注入链路的终点。
- 集中路由的价值：更换供应商只需改 magpie 配置，不必改动 [[tdai-proxy]]。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
