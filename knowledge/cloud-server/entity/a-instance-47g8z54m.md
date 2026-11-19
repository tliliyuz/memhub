---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/a-instance-47g8z54m
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/服务器-a-instance-47g8z54m.md
  type: wiki
supersedes: []
tags:
- 宿主机
- 百度智能云
- clickhouse
- 双机
tier: canonical
title: 服务器 A（instance-47g8z54m）
updated_at: '2026-11-18T07:26:22Z'
---

> 百度智能云上的 ClickHouse 专用主机（2 vCPU / 1886 MiB / 40 GiB，无 swap、无容器），是本知识库记录的第二台宿主机。

# 定义

服务器 A（主机名 `instance-47g8z54m`，公网 120.48.25.220，内网 192.168.16.2）是
[[百度智能云]] 上的一台云服务器，**唯一业务角色**是运行 [[ClickHouse]] 列式分析数据库。
它与承担记忆栈与公网入口的 [[腾讯云 CVM VM-0-10-ubuntu]]（B 机）共同构成
[[双机角色分工]] 的两端。

快照时间：2026-11-11 13:42（UTC+8）。

# 关键属性

## 基础配置

| 项目 | 值 |
|---|---|
| 公网 IP | 120.48.25.220 |
| 内网 IP | 192.168.16.2 |
| 操作系统 | Ubuntu 22.04.5 LTS |
| 内核 | 5.15.0-181-generic |
| 架构 | x86_64 |
| CPU | Intel Xeon Gold 6271C @ 2.60GHz，2 vCPU（1 core × 2 threads） |
| 内存 | 1886 MiB（约 1.8 GiB） |
| Swap | **无** |
| 系统盘 | 40 GiB ext4，已用 18 GiB（48%），可用 20 GiB |
| 连续运行 | 61 天 21 小时 |
| 云厂商 | [[百度智能云]] |

## 软件与角色

| 组件 | 版本/状态 | 说明 |
|---|---|---|
| [[ClickHouse]] | 26.9.1.1101 | `clickhouse-server.service`，原生进程（非容器） |
| Docker | 未安装 | 本机无任何容器 |
| [[magpie gateway]] | 已迁走（2026-11-11） | 现运行在 B 机 43.142.18.23 |
| [[百度智能云主机安全与管理组件]] | 运行中 | `bcm-agent`、`checkmce`、`bsm-agent`、`has-agent`，**不要停止或修改** |

## 端口与绑定

| 服务 | 端口 | 绑定地址 | 公网可达 |
|---|---|---|---|
| SSH | 22 | 0.0.0.0 | 是 |
| SSH | 2222 | 0.0.0.0 | 是 |
| ClickHouse HTTP | 8123 | 127.0.0.1 | 否 |
| ClickHouse native | 9000 | 127.0.0.1 | 否 |
| ClickHouse MySQL 协议 | 9004 | 127.0.0.1 | 否 |
| ClickHouse PostgreSQL 协议 | 9005 | 127.0.0.1 | 否 |
| ClickHouse interserver | 9009 | 127.0.0.1 | 否 |
| bcm-agent | 781 | 0.0.0.0 | 是（云厂商组件） |
| checkmce | 428 | 0.0.0.0 | 是（云厂商组件） |
| [[systemd-resolved]] | 53 | 127.0.0.53 | 否 |

数据库类端口一律只绑回环，外部应用必须经 SSH 隧道或内网访问，见
[[回环绑定与 SSH 隧道访问]]。

## 资源占用

| 指标 | 值 |
|---|---|
| 总内存 | 1886 MiB |
| 已用 | 754 MiB |
| 可用 | 945 MiB |
| buff/cache | 829 MiB |
| Swap | 无，内存耗尽只能 OOM |
| 负载 | 0.10 / 0.05 / 0.04 |
| 磁盘 | 40 GiB，已用 18 GiB（48%） |

主要进程：`clickhouse` 约 19% 内存、5% CPU；其余为系统与云厂商 agent。

## 安全现状

| 项 | 状态 |
|---|---|
| ufw | 未启用 |
| iptables | 默认 ACCEPT，另有 fail2ban 的 `f2b-sshd` 链 |
| SSH 端口 | 22 与 2222 双端口 |
| root 登录 | `PermitRootLogin without-password`（仅密钥） |
| 密码认证 | **已关闭**（`PasswordAuthentication no`） |
| MaxAuthTries | 6 |
| [[fail2ban]] | 已安装并从 iptables 规则看已生效，当前封禁 5 个来源 IP |

已封禁来源 IP（示例）：`163.5.210.138`、`139.162.171.111`、`194.59.30.196`、
`113.200.238.158`、`195.178.110.218`。

安全层次与 B 机不同：A 机**没有 nginx 公网收口层**，实际构成为
云厂商边界/agent → [[fail2ban]] → SSH 密钥-only + 双端口，详见 [[主机安全防护分层]]。

# 关系

| 对象 | 关系 |
|---|---|
| [[ClickHouse]] | 宿主—服务：A 机唯一的业务负载 |
| [[百度智能云]] | 云厂商归属，提供主机与安全/管理 agent |
| [[百度智能云主机安全与管理组件]] | 与业务共置同宿主，不可变更 |
| [[腾讯云 CVM VM-0-10-ubuntu]] | 姊妹主机，经 [[双机角色分工]] 分工 |
| [[magpie gateway]] | 迁移前宿主（2026-11-11 迁出到 B 机） |
| [[管理员账号]] | 运维入口 `root@120.48.25.220`，仅密钥 |
| [[systemd-resolved]] | 本地 DNS 解析器（127.0.0.53:53） |
| [[资源配额与 OOM 风险]] | 无 swap + 1.8G 内存的 OOM 风险场景 |
| [[容器化部署与重建语义]] | 原生 systemd 进程的反例：运行期改动**可**持久 |

# 运维要点

```bash
systemctl status clickhouse-server
clickhouse-client --query "select version()"
journalctl -u clickhouse-server -n 100
fail2ban-client status sshd
ss -tulpn | grep clickhouse
```

1. `checkmce`、`bcm-agent`、`bsm-agent`、`has-agent` 是云厂商主机安全/管理组件，
   **不要重启、停止或改动**（[[云厂商托管组件约束]]）。
2. 本机无 swap，内存仅 1.8G，ClickHouse 大查询可能触发 OOM；大批量分析建议限流。
3. ClickHouse 只监听回环，远程查询走 SSH 隧道：
   `ssh -L 8123:127.0.0.1:8123 root@120.48.25.220`。
4. 磁盘使用率 48%，接近一半，建议关注增长。

# Citations

- `server-a-clickhouse.md`（2026-11-11 13:42 UTC+8 实测快照）
