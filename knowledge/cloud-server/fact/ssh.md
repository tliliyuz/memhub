---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/ssh
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/回环绑定与-ssh-隧道访问.md
  type: wiki
supersedes: []
tags:
- 安全
- 网络
- 最小暴露
- 端口绑定
tier: canonical
title: 回环绑定与 SSH 隧道访问
updated_at: '2026-11-18T07:26:22Z'
---

> 数据库与内部服务一律只绑 127.0.0.1，远程访问必须经 ssh -L 隧道或内网，是「不新增公网暴露面」原则在非 Web 服务上的体现。

# 定义

回环绑定与 SSH 隧道访问是一种网络暴露策略：服务的监听地址不设为 `0.0.0.0`，而只设
`127.0.0.1`，从而在**操作系统层面**而非仅靠防火墙保证「公网不可达」；需要远程访问时，
借 SSH 的本地端口转发建立临时通道。

它与 [[minimal-exposure-binding]] 描述的是同一条最小暴露原则的两种表述：前者面向
**非 Web 的内部服务**（数据库、代理端口），后者是总括命名；建议以本页为规范页，两页互链归一。

# Schema

| 要素 | 说明 |
|---|---|
| 绑定地址 | `127.0.0.1`（或 docker0 等仅主机可路由地址） |
| 访问通道 | `ssh -L <local>:127.0.0.1:<remote> user@host` |
| 适用对象 | 数据库、内部 API、管理面板 |
| 不适用对象 | 需公开访问的 Web 入口（交由 [[nginx]] 单点收口） |

# Examples

## 服务器 A：ClickHouse 全端口回环

| 协议 | 端口 | 绑定 |
|---|---|---|
| HTTP | 8123 | 127.0.0.1 |
| native | 9000 | 127.0.0.1 |
| MySQL | 9004 | 127.0.0.1 |
| PostgreSQL | 9005 | 127.0.0.1 |
| interserver | 9009 | 127.0.0.1 |

```bash
ssh -L 8123:127.0.0.1:8123 root@120.48.25.220
```

外部应用（BI、脚本、客户端）一律经隧道或内网访问，A 机因此不需要为数据库开任何公网规则。

## 服务器 B：记忆栈内部端口

[[腾讯云 CVM VM-0-10-ubuntu]] 上同类实例包括：[[tdai-memory-core]] 8420、
[[tdai-memory-hub]] 的 8125 / 8424、[[tdai-proxy]] 8096、[[magpie gateway]] 的
172.17.0.1:3425 与 web UI 127.0.0.1:3430、[[systemd-resolved]] 的 127.0.0.53:53。
[[Claude Code 与 Agent 客户端]] 目前即通过 SSH 隧道访问 8096。

# 意义

1. 暴露面收敛在**进程配置层**，即使防火墙被误改为 ACCEPT（A 机 iptables 默认 ACCEPT、
   ufw 未启用）数据库仍不可从公网直连。
2. 与 [[单入口反向代理架构]] 互补：Web 流量走 [[nginx]] 收口，数据/内部流量走隧道。
3. 代价是运维必须维护隧道，故 [[运维操作手册]] 中的远程操作步骤依赖 SSH 可用性；
   一旦 SSH 被封禁（[[fail2ban]] 误封），所有内部服务同时失去远程访问。

# 关系

| 对象 | 关系 |
|---|---|
| [[ClickHouse]] | 回环绑定实例（A 机） |
| [[tdai-proxy]] / [[tdai-memory-hub]] / [[tdai-memory-core]] | 回环绑定实例（B 机） |
| [[minimal-exposure-binding]] | 同一原则的总括表述，宜归一 |
| [[单入口反向代理架构]] | Web 侧的对偶策略 |
| [[主机安全防护分层]] | 本策略是 SSH 认证层之外的结构性防线 |

# Citations

- `server-a-clickhouse.md` §3 端口与绑定、§6 运维注意事项 3
- `cloud-server.md`（B 机回环端口）
