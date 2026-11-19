---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/n-fe5a2fd4
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/双机角色分工.md
  type: wiki
supersedes: []
tags:
- 架构
- 主机规划
- 双机
tier: canonical
title: 双机角色分工
updated_at: '2026-11-18T07:26:22Z'
---

> 两台主机的职责切分——服务器 A 承担 ClickHouse 数据分析，服务器 B 承担 memhub 记忆栈 + magpie + nginx 公网入口，解释了 magpie 迁移方向与 A 机无容器的成因。

# 定义

双机角色分工指本知识库记录的两台宿主机之间的职责边界：

- **A 机**（[[服务器 A（instance-47g8z54m）]]，百度智能云 120.48.25.220）：**纯数据分析节点**，
  只跑 [[ClickHouse]] 原生进程，无 Docker、无公网 Web 入口。
- **B 机**（[[腾讯云 CVM VM-0-10-ubuntu]]，腾讯云 43.142.18.23）：**记忆栈与应用入口节点**，
  跑 memhub 三件套（[[tdai-memory-core]] / [[tdai-memory-hub]] / [[tdai-proxy]]）+
  [[magpie gateway]] + [[nginx]]。

# 对比表（原文 §7）

| 项目 | A（服务器 A） | B（cloud-server） |
|---|---|---|
| 公网 IP | 120.48.25.220 | 43.142.18.23 |
| 云厂商 | [[百度智能云]] | 腾讯云 |
| 规格 | 2 vCPU / 1.8G / 40G | 4 vCPU / 3.6G / 40G |
| 系统 | Ubuntu 22.04 | Ubuntu 24.04 |
| 主要负载 | [[ClickHouse]] 26.9 | memhub 三件套 + [[magpie gateway]] + [[nginx]] |
| 容器 | 无（原生 systemd） | 3 个（core / hub / proxy） |
| 公网入口 | SSH 双端口 + 云厂商 agent | 22 / 80 / 443（[[memhub.work 域名]]） |
| [[fail2ban]] | 已启用 | 已启用（2026-11-11） |
| 密码登录 | 已关闭 | 仍开启（待收紧） |
| swap | 无 | 1.9G |

# 意义

1. **迁移方向的解释力**：[[magpie gateway]] 于 2026-11-11 由 A 机迁至 B 机，符合
   「B 机集中承载运行时依赖（模型路由）+ 公网入口，A 机专注存储与计算」的分工逻辑。
2. **无容器的成因**：A 机是单服务主机，无需编排与重建语义，因此直接用
   `clickhouse-server.service` 原生进程；与 B 机的
   [[容器化部署与重建语义]] 形成两种相反的运行期持久化语义。
3. **暴露面收敛**：A 机除 SSH 与云厂商 agent 外无公网入口，B 机才有
   [[单入口反向代理架构]] 的 80/443。
4. **安全收紧程度差异**：A 机密码认证已关闭、B 机仍开启，构成
   [[主机安全防护分层]] 在双机上的差异化落地。
5. **风险画像不同**：B 机是「容器无限制导致整机 OOM」，A 机是「无 swap + 大查询 OOM」，
   两种成因并列于 [[资源配额与 OOM 风险]]。

# 常见话题

- 系统架构 / 部署模型：单服务节点 vs 多容器应用节点
- 数据流：分析型数据库与记忆栈彼此独立（无跨机调用被记录）
- 权限模型：A 机仅密钥、双端口，B 机保留密码登录待收紧

# 关系

[[服务器 A（instance-47g8z54m）]] ↔ [[腾讯云 CVM VM-0-10-ubuntu]]
（以本概念为中介）；[[ClickHouse]] ↔ [[magpie gateway]] ↔ [[nginx]] 分别落在两台意主机的
职责带上（ClickHouse 归 A，其余归 B）。

# Citations

- `server-a-clickhouse.md` §7 两台服务器对比
- `cloud-server.md`（B 机侧事实）
