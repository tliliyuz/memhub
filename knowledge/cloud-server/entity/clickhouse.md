---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/clickhouse
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/clickhouse.md
  type: wiki
supersedes: []
tags:
- 数据库
- 分析
- 回环绑定
- systemd
tier: canonical
title: ClickHouse
updated_at: '2026-11-18T07:26:22Z'
---

> 列式分析数据库（26.9.1.1101），在服务器 A 上以 clickhouse-server.service 原生进程运行，全部协议端口只绑回环。

# 定义

ClickHouse 是 [[服务器 A（instance-47g8z54m）]] 上唯一的业务服务：一台列式（columnar）分析型
数据库，版本 **26.9.1.1101**，由 systemd 单元 `clickhouse-server.service` 以**原生进程**方式托管
（非容器，见 [[容器化部署与重建语义]]）。

# Schema

## 监听端口

| 协议 | 端口 | 绑定地址 | 公网可达 |
|---|---|---|---|
| HTTP | 8123 | 127.0.0.1 | 否 |
| native（TCP） | 9000 | 127.0.0.1 | 否 |
| MySQL 协议 | 9004 | 127.0.0.1 | 否 |
| PostgreSQL 协议 | 9005 | 127.0.0.1 | 否 |
| interserver | 9009 | 127.0.0.1 | 否 |

**全系列端口只绑 127.0.0.1**，外部应用必须经 SSH 隧道或内网访问——这是
[[回环绑定与 SSH 隧道访问]] 的典型实例。

# 关键属性

- 资源：约 19% 内存、5% CPU（宿主机 1886 MiB 中约 1/5）。
- 宿主无 swap，因此**大查询可直接触发整机 OOM**，见 [[资源配额与 OOM 风险]]。
- 磁盘：与系统共用 40 GiB 系统盘（已用 48%），数据增长直接体现为系统盘水位上升。
- 多协议兼容（HTTP / native / MySQL / PostgreSQL）意味着现有 MySQL/PostgreSQL 客户端
  可复用，但访问层仍需隧道。

# 运维

```bash
systemctl status clickhouse-server
clickhouse-client --query "select version()"
journalctl -u clickhouse-server -n 100
ss -tulpn | grep clickhouse
```

远程查询隧道：

```bash
ssh -L 8123:127.0.0.1:8123 root@120.48.25.220
```

注意事项：

1. 大批量分析建议限流，避免在 1.8G 无 swap 主机上打满内存。
2. 关注系统盘使用率（当前 48%）。

# 关系

| 对象 | 关系 |
|---|---|
| [[服务器 A（instance-47g8z54m）]] | 宿主（唯一业务负载） |
| [[magpie gateway]] | 无直接耦合；magpie 已迁至 B 机，A 机仅剩分析负载 |
| [[双机角色分工]] | A 机承担「数据分析」职责的载体 |
| [[管理员账号]] | 运维者以 `root` 密钥登录后本地操作 |

# Citations

- `server-a-clickhouse.md` §2 角色与软件、§3 端口与绑定、§4 资源占用、§6 运维
