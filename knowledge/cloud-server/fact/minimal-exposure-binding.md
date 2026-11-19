---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/minimal-exposure-binding
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/minimal-exposure-binding.md
  type: wiki
supersedes: []
tags:
- 安全
- 网络
- 最小暴露
tier: canonical
title: minimal-exposure-binding
updated_at: '2026-11-18T07:26:22Z'
---

> 最小暴露绑定原则的总括页面——只绑定必要地址、只开放必要端口；现以服务器 A 的 ClickHouse 全端口回环为第二实例。

# 定义

minimal-exposure-binding 指主机与服务在**绑定与端口**两个层面同时做最小化：
服务只监听必要地址（优先 `127.0.0.1` 或 docker0 等主机内部地址），主机只开放必要端口。

本页为总括页；具体的做法、实例与运维含义以
[[回环绑定与 SSH 隧道访问]] 为规范描述页（两者为同一原则的两种表述，宜互链归一）。

# Examples

| 实例 | 主机 | 说明 |
|---|---|---|
| [[ClickHouse]] 8123 / 9000 / 9004 / 9005 / 9009 | [[服务器 A（instance-47g8z54m）]] | 全部只绑 127.0.0.1，远程走 `ssh -L` |
| [[tdai-proxy]] 8096、[[tdai-memory-hub]] 8125/8424、[[tdai-memory-core]] 8420 | [[腾讯云 CVM VM-0-10-ubuntu]] | 容器端口仅回环 |
| [[magpie gateway]] | B 机（原 A 机） | 172.17.0.1:3425（仅网桥可达）+ UI 127.0.0.1:3430 |
| [[systemd-resolved]] 53 | 两台 | 127.0.0.53 |
| [[nginx]] 443 | B 机 | 唯一**有意**公开的入口（[[单入口反向代理架构]]） |

# 反面情形（需标注）

- A 机 [[fail2ban]] 已生效但 **ufw 未启用、iptables 默认 ACCEPT**，
  最小暴露因此**完全依赖绑定地址**而非防火墙规则。
- A 机公网仍有 SSH 22 / 2222 与云厂商 agent 781 / 428，这些是必要或不可控的例外
  （[[云厂商托管组件约束]]）。

# 关系

[[回环绑定与 SSH 隧道访问]]（规范页）· [[单入口反向代理架构]]（Web 侧对偶）·
[[主机安全防护分层]]（本原则是其结构性一层）

# Citations

- `server-a-clickhouse.md` §3 端口与绑定
- `cloud-server.md`（B 机绑定事实）
