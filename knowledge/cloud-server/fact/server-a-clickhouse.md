---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/server-a-clickhouse
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/sources/server-a-clickhouse-运维快照.md
  type: wiki
supersedes: []
tags:
- 运维快照
- clickhouse
- 百度智能云
- 主机基线
tier: canonical
title: server-a-clickhouse 运维快照
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-11-11 对第二台宿主机「服务器 A」（百度智能云 instance-47g8z54m）的实测运维快照，记录其基础配置、ClickHouse 原生单服务角色、回环端口绑定、无 swap 资源约束、安全现状与运维注意事项。

# 文档信息

| 项 | 值 |
|---|---|
| 快照时间 | 2026-11-11 13:42（UTC+8） |
| 主机名 | instance-47g8z54m |
| 公网 IP | 120.48.25.220 |
| 对应页面 | [[服务器 A（instance-47g8z54m）]] |
| 姊妹快照 | [[cloud-server 运维快照]]（B 机，2026-11-11） |

# 内容摘要

本文件是本知识库首次把「服务器 A / 百度智能云 / ClickHouse」这条独立分支纳入记录，与既有的
[[cloud-server 运维快照]] 构成同一批次的双机对照快照。

1. **基础配置**：2 vCPU（Xeon Gold 6271C）、1886 MiB 内存、**无 swap**、40 GiB 系统盘已用 48%、
   连续运行 61 天 21 小时；云厂商依据 `bcm-agent` / `checkmce` / `bsm-agent` / `has-agent` 判定为
   [[百度智能云]]。
2. **角色与软件**：唯一业务负载是 [[ClickHouse]] 26.9.1.1101，以 `clickhouse-server.service`
   **原生进程**方式运行；**未安装 Docker**，无任何容器。
3. **magpie 迁移事实**：模型网关 [[magpie gateway]] 已于 2026-11-11 从 A 机迁往 B 机
   （[[腾讯云 CVM VM-0-10-ubuntu]]，43.142.18.23），A 机不再是 magpie 的宿主。
4. **端口与绑定**：ClickHouse 的 HTTP 8123 / native 9000 / MySQL 9004 / PostgreSQL 9005 /
   interserver 9009 全部只绑 127.0.0.1；对外仅 SSH 22 与 2222，以及云厂商 agent 占用 781、428。
   这是 [[回环绑定与 SSH 隧道访问]] 原则的第二个实例。
5. **资源现状**：已用 754 MiB / 可用 945 MiB / buff-cache 829 MiB，负载 0.10；无 swap 意味着内存
   耗尽只能 OOM——见 [[资源配额与 OOM 风险]] 的 A 机变体。
6. **安全现状**：ufw 未启用；iptables 默认 ACCEPT 并已接入 fail2ban 的 `f2b-sshd` 链；
   `PermitRootLogin without-password`、`PasswordAuthentication no`、`MaxAuthTries 6`；
   [[fail2ban]] 已生效，当前封禁 5 个来源 IP。
7. **运维约束**：`checkmce` / `bcm-agent` / `bsm-agent` / `has-agent` 属云厂商部件，
   **不可重启、停止或改动**（见 [[云厂商托管组件约束]]）。
8. **双机对比**：给出 A（百度智能云，2C/1.8G/40G，无容器，密码登录已关闭，无 swap）与
   B（腾讯云，4C/3.6G/40G，三容器 + magpie + nginx，密码登录待收紧，1.9G swap）的逐项对比，
   支撑 [[双机角色分工]] 概念。

# 运维命令清单（原文摘录）

```bash
systemctl status clickhouse-server
clickhouse-client --query "select version()"
journalctl -u clickhouse-server -n 100
fail2ban-client status sshd
ss -tulpn | grep clickhouse
```

远程查询隧道：`ssh -L 8123:127.0.0.1:8123 root@120.48.25.220`。

# Citations

- 原文：`server-a-clickhouse.md`（快照时间 2026-11-11 13:42 UTC+8）
- 对照：[[cloud-server 运维快照]]
