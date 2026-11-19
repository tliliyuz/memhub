---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/cloud-server
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/sources/cloud-server-运维快照.md
  type: wiki
supersedes: []
tags:
- 基础设施
- 运维
- baseline
- 快照
- memhub
tier: canonical
title: cloud-server 运维快照
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-11-11 对单台腾讯云 CVM 主机 VM-0-10-ubuntu 的实测运维快照，记录自托管 memhub 记忆栈的配置、拓扑、端口、资源、证书与安全现状。

# cloud-server 运维快照

## 文档概况

- **类型**：基础设施 / 运维快照（单个时间点的实测状态），非需求文档也非架构设计文档，故 `source_type` 记为 `other`。
- **快照时间**：2026-11-11 13:20（UTC+8）
- **对象**：单台腾讯云 CVM 主机 `VM-0-10-ubuntu`
- **价值定位**：本知识库中所有服务实体的**实测基线（baseline）**；描述"机器此刻到底是什么样"，而概念页承载"为什么这样设计"。

## 核心内容摘要

### 1. 基础配置

| 项目 | 值 |
|---|---|
| 云厂商 | 腾讯云 CVM |
| 公网 IP | 43.142.18.23 |
| 内网 IP | 10.0.0.10 |
| 操作系统 | Ubuntu 24.04 LTS / 内核 6.8.0-49-generic / x86_64 |
| CPU | AMD EPYC 7K62，4 vCPU（1 socket × 4 core × 1 thread） |
| 内存 | 3659 MiB；Swap 1987 MiB（`/swap.img`） |
| 系统盘 | 40 GiB ext4，已用 9.2 GiB（25%） |
| 域名 | `memhub.work` / `www.memhub.work`（阿里云 DNS A 记录 → 43.142.18.23） |
| Docker | 27.5.1 |

宿主实体见 [[腾讯云 CVM VM-0-10-ubuntu]]，域名与解析见 [[memhub.work 域名]]、[[阿里云 DNS]]。

### 2. 服务拓扑

两条方向相反的调用链，详见 [[记忆栈服务拓扑]]：

```
Claude Code / Agent → 127.0.0.1:8096 (tdai-proxy)
  → 172.17.0.1:3425 (magpie gateway) → 上游供应商

浏览器 → https://memhub.work (nginx:443)
  → 127.0.0.1:8125 (tdai-memory-hub 面板)
      ├─ 127.0.0.1:8424 (knowledge)
      └─ 127.0.0.1:8420 (tdai-memory-core)
```

### 3. 端口与绑定

| 服务 | 端口 | 绑定地址 | 公网可达 |
|---|---|---|---|
| SSH | 22 | 0.0.0.0 | 是 |
| nginx HTTP | 80 | 0.0.0.0 | 是（301 → 443） |
| nginx HTTPS | 443 | 0.0.0.0 | 是 |
| tdai-proxy | 8096 | 127.0.0.1 | 否 |
| tdai-memory-hub panel | 8125 | 127.0.0.1 | 否（经 nginx 反代） |
| tdai-memory-hub knowledge | 8424 | 127.0.0.1 | 否 |
| tdai-memory-core | 8420 | 127.0.0.1 | 否 |
| magpie gateway | 3425 | 172.17.0.1（docker0） | 否（容器可达） |
| magpie web UI | 3430 | 127.0.0.1 | 否 |
| systemd-resolved | 53 | 127.0.0.53 / 127.0.0.54 | 否 |

**原则**：除 22/80/443 外一律只绑回环或 docker0，容器端口都带 `127.0.0.1:` 前缀 → 见 [[最小暴露面绑定原则]]、[[单入口反向代理架构]]。

### 4. 资源占用

主机：总内存 3659 MiB，已用 1539 MiB，可用 2119 MiB，buff/cache 2162 MiB，Swap 使用 0，负载 0.08 / 0.04 / 0.05。

| 容器 | 镜像 | 实际内存 | CPU | memory limit |
|---|---|---|---|---|
| tdai-memory-core | agentmemory/memory-core:latest | 646.7 MiB (17.7%) | 2.1% | 未限制（0） |
| tdai-memory-hub | agentmemory/memory-hub:latest | 103.7 MiB (2.8%) | 0.02% | 未限制（0） |
| tdai-proxy | agentmemory/memory-proxy:latest | 87.9 MiB (2.4%) | 0.2% | 未限制（0） |

容器合计约 840 MiB；magpie 为宿主机原生进程，不计入容器统计。风险分析见 [[资源配额与 OOM 风险]]。

数据卷：`tdai-memory-core-data` 320.5 MB（L0/L1、skills、SQLite meta 库）、`tdai-panel-data` 9.3 MB（面板配置、knowledge 数据）→ 见 [[Docker 卷数据持久化]]。

### 5. 域名与证书

- 解析：阿里云 DNS（dns27/dns28.hichina.com），`@` 与 `www` A 记录 → 43.142.18.23
- 证书：Let's Encrypt，certbot `--nginx` 插件 + HTTP-01 校验
- 签发 2026-11-11 03:58 UTC，到期 2027-02-09 03:58 UTC，`certbot.timer` 自动续期
- 路径：`/etc/letsencrypt/live/memhub.work/`
- 与阿里云无关：免费证书，只要求域名解析到本机且 80 端口可达

机制详见 [[TLS 证书自动续期]]、[[Let's Encrypt 与 certbot]]。

### 6. 安全现状

| 项 | 状态 |
|---|---|
| ufw | 未启用（依赖腾讯云安全组） |
| iptables 默认策略 | ACCEPT，仅腾讯自带的 `YJ-FIREWALL-INPUT` 有针对性封禁 |
| SSH 端口 | 22 |
| root 登录 | `PermitRootLogin without-password`（禁 root 密码，允许密钥） |
| 密码认证 | **仍开启**（`PasswordAuthentication yes`） |
| MaxAuthTries | 6 |
| fail2ban | 1.0.2，启用 `sshd` jail |
| nginx 限流 | `/api/v1/auth/` 6 次/分（burst 4），其余 30 次/秒（burst 60） |
| 安全头 | nosniff / SAMEORIGIN / no-referrer / 隐藏 nginx 版本 |

fail2ban 策略：`findtime=10m, maxretry=5, bantime=1h`，递增封禁（×2，上限 1 周）；白名单 `127.0.0.1`、`180.173.121.131`。
近 7 天 SSH 失败 11 次，主要来源 `77.239.124.46`（8 次，已被腾讯云防火墙 REJECT）；唯一成功登录来源 `180.173.121.131`（本人）。

分层视角见 [[主机安全防护分层]]。

### 7. 目录与运维

| 路径 | 用途 |
|---|---|
| `/opt/memhub` | 三件套启动脚本、`.env`、`.admin-key`（均 600） |
| `/etc/nginx/sites-available/memhub` | 公网入口配置 |
| `/etc/nginx/proxy_params_memhub` | 反代公共参数 |
| `/etc/fail2ban/jail.local` | fail2ban 策略 |
| `/root/.config/magpie/settings.json` | magpie 配置（含 lanKey） |

systemd 单元：`memhub-stack.service`（oneshot，按 core → hub → proxy 拉起）、`magpie-gateway.service`、`nginx.service`、`docker.service`、`fail2ban.service`。见 [[memhub-stack 服务单元]]、[[容器化部署与重建语义]]、[[运维操作手册]]。

### 8. 已知限制与待办

1. 三容器均未设内存上限，内存失控会 OOM 整机；建议 core 1536m、hub 512m、proxy 512m，且必须同时写进启动脚本（systemd 会重建容器）。
2. SSH 密码认证仍开启，建议在确认密钥可用后关闭 `PasswordAuthentication`。
3. ufw 未启用，若要在安全组之外再加一层主机防火墙，可放行 22/80/443 后启用。
4. 8096 未做公网暴露，外部客户端依赖 SSH 隧道；后续可加独立子域名 + 反代做鉴权。
5. 数据卷尚无自动备份策略（当前依赖手工快照）。

## 相关页面

- 宿主与网络：[腾讯云 CVM VM-0-10-ubuntu]]、[[memhub.work 域名]]、[[阿里云 DNS]]、[[腾讯云安全组]]
- 服务：[nginx]]、[[tdai-memory-hub]]、[[tdai-memory-core]]、[[tdai-proxy]]、[[magpie gateway]]、[[Docker]]
- 防护：[fail2ban]]、[[主机安全防护分层]]、[[管理员账号]]
- 设计约束：[最小暴露面绑定原则]]、[[单入口反向代理架构]]、[[资源配额与 OOM 风险]]、[[Docker 卷数据持久化]]

## Citations

- 本页内容全部来自 `cloud-server.md`（2026-11-11 13:20 UTC+8 快照）。所有实体页 / 概念页在 `sources` 字段中回指本文。
