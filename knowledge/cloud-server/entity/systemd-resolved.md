---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/systemd-resolved
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/systemd-resolved.md
  type: wiki
supersedes: []
tags:
- 基础组件
- dns
- 双机
tier: canonical
title: systemd-resolved
updated_at: '2026-11-18T07:26:22Z'
---

> 主机本地 DNS 解析器，监听 127.0.0.53 / 127.0.0.54 的 53 端口；已确认同时存在于服务器 A 与服务器 B。

# 定义

systemd-resolved 是 Ubuntu 默认的本地 DNS 解析器，作为 stub resolver 监听回环地址的 53 端口，
把主机内应用的解析请求转发到上游 DNS。

# 关键属性

| 项 | 值 |
|---|---|
| 监听 | 127.0.0.53:53（另见 127.0.0.54:53） |
| 公网可达 | 否（仅回环） |
| 出现主机 | [[服务器 A（instance-47g8z54m）]]（127.0.0.53:53）、[[腾讯云 CVM VM-0-10-ubuntu]] |

# 意义

- 它是两台 Ubuntu 主机（22.04 / 24.04）**共性基础组件**，不随角色分工变化。
- 其回环绑定是 [[回环绑定与 SSH 隧道访问]] 原则在系统级组件上的自然体现
  （默认即安全，无需额外加固）。
- 与业务无关，排查 DNS 问题时应先确认它而非 [[nginx]] 或容器网络。

# 关系

| 对象 | 关系 |
|---|---|
| [[服务器 A（instance-47g8z54m）]] | 宿主机 |
| [[腾讯云 CVM VM-0-10-ubuntu]] | 宿主机 |
| [[阿里云 DNS]] | 外部权威 DNS（memhub.work 域名解析），不同层 |

# Citations

- `server-a-clickhouse.md` §3 端口与绑定（systemd-resolved 127.0.0.53:53）
- `cloud-server.md`（同组件在 B 机的监听）
