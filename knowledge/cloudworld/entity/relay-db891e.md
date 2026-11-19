---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloudworld/entity/relay-db891e
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/本地-relay.md
  type: wiki
supersedes: []
tags:
- relay
- 本地进程
- 请求链路
tier: canonical
title: 本地 relay
updated_at: '2026-11-18T07:26:22Z'
---

> cloud-world 桌面端运行期的本地依赖进程，是真实请求链路的起点，具备独立的生命周期与 bridge 端口状态语义。

# 本地 relay

## 定义

[[cloud-world 桌面端]] 运行期的本地依赖服务，是 [[真实请求链路]] 的起点：外部请求经它转发到云端 proxy，再到 magpie。

## 关键属性

- 进程状态可用 `status` 查询；验收结束后必须确认生产 relay 仍在运行、bridge 端口正常。
- 存在「生产 relay」与「隔离测试用 relay」两种实例，后者在一次性 profile 下运行（见 [[隔离测试]]）。
- 配置耦合：`apply` 会创建/修改 `settings.json`，若先停 relay 再还原配置，会留下指向已停 relay 的配置。
- 可能在 `target\debug\cloud-world.exe` 上被 watchdog 占用，因此验收构建输出需改道 `target-build\`。

## 关系

- 属于 [[cloud-world 桌面端]] 的运行期依赖。
- [[真实请求链路]] 的第一个节点。
- 测试由 `relay` crate 承担：5 个单元/集成 + 16 个集成测试（见 [[实测口径]]）。

# Citations

- [[08-验收证据分层]]
