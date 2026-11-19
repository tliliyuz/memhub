---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/fail2ban
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/fail2ban.md
  type: wiki
supersedes: []
tags:
- 安全
- ssh
- 双机
tier: canonical
title: fail2ban
updated_at: '2026-11-18T07:26:22Z'
---

> 主机侧 SSH 暴力破解防护（1.0.2），在服务器 A 与服务器 B 两台主机上均已部署，启用 sshd jail、递增封禁与白名单。

# 定义

fail2ban 是主机侧的入侵防护工具（版本 1.0.2），通过读取认证日志并写入 iptables 规则，
对暴力破解来源 IP 做**递增式封禁**。本知识库现记录两台主机**均已部署**：

| 主机 | 状态 | 备注 |
|---|---|---|
| [[服务器 A（instance-47g8z54m）]] | 已安装并生效 | iptables 中存在 `f2b-sshd` 链，当前封禁 **5 个**来源 IP |
| [[腾讯云 CVM VM-0-10-ubuntu]] | 已启用（2026-11-11） | 配置两个白名单 IP |

# Schema

- Jail：`sshd`
- 规则载体：iptables 自定义链 `f2b-sshd`（A 机实测可见）
- 策略：递增封禁（多次触发后封禁时长增长）
- 白名单：B 机配置两个白名单 IP，其中包含 [[管理员账号]] 的来源地址
- 查询命令：`fail2ban-client status sshd`

# Examples

## 服务器 A 的封禁样本

当前封禁来源 IP（示例）：

`163.5.210.138`、`139.162.171.111`、`194.59.30.196`、`113.200.238.158`、`195.178.110.218`

A 机 ufw 未启用、iptables 默认策略为 ACCEPT，因此 `f2b-sshd` 链是主机内**唯一实际的
动态封禁手段**，构成 [[主机安全防护分层]] 的第二层。

# 意义与风险

1. 双机部署使 SSH 爆破防护不依赖单台主机；但两台主机的 SSH 端口不同——
   A 机 22 + 2222 双端口，需要确认 jail 对两个端口均生效。
2. 误封风险：A 机全部内部服务都靠 SSH 隧道访问（[[回环绑定与 SSH 隧道访问]]），
   一旦运维者 IP 被误封，数据库访问同时中断。
3. A 机密码认证已关闭（仅密钥），爆破成功率极低，fail2ban 在此更多是**降噪**与
   日志保护手段；B 机密码登录仍开启，fail2ban 承压更重。

# 关系

| 对象 | 关系 |
|---|---|
| [[服务器 A（instance-47g8z54m）]] | 部署主机（`f2b-sshd` 链） |
| [[腾讯云 CVM VM-0-10-ubuntu]] | 部署主机（含白名单） |
| [[管理员账号]] | 白名单持有者 |
| [[主机安全防护分层]] | 第 2 层（动态封禁） |
| [[运维操作手册]] | 含 fail2ban 状态检查步骤 |

# Citations

- `server-a-clickhouse.md` §5 安全现状
- `cloud-server.md`（B 机 fail2ban 配置）
