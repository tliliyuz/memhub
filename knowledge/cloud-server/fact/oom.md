---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/oom
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/资源配额与-oom-风险.md
  type: wiki
supersedes: []
tags:
- 容量
- 资源限制
- 风险
- 资源
- 内存
- oom
- 双机
tier: canonical
title: 资源配额与 OOM 风险
updated_at: '2026-11-18T07:26:22Z'
---

> 两台宿主机各自不同的 OOM 成因——B 机三容器 memory limit 均为 0 而宿主仅 3659 MiB；A 机无 swap、内存仅 1886 MiB，ClickHouse 大查询即可打爆整机。

# 资源配额与 OOM 风险

## 定义

资源配额与 OOM 风险指容器/进程的内存上限与宿主机物理内存不匹配时，单点内存失控会引发**整机 OOM** 并连带杀死其他服务。当前 [[Docker]] 三个容器均**未设置内存上限**（`memory limit = 0`），而 [[腾讯云 CVM VM-0-10-ubuntu]] 总内存仅 3659 MiB、Swap 1987 MiB。任一容器内存泄漏或流量尖峰都会把整机拖入 OOM，进而同时中断 [[记忆栈服务拓扑]] 的两条链路。

两台主机的风险成因**不同**，需分别治理：B 机是容器侧失控，A 机是无 swap + 大查询。

## 服务器 B（容器侧失控）

### 现状数据（快照时刻）

| 容器 | 实际内存 | 占比 | limit |
|---|---|---|---|
| [[tdai-memory-core]] | 646.7 MiB | 17.7% | 0 |
| [[tdai-memory-hub]] | 103.7 MiB | 2.8% | 0 |
| [[tdai-proxy]] | 87.9 MiB | 2.4% | 0 |

容器合计约 840 MiB；主机已用 1539 MiB、可用 2119 MiB、Swap 使用 0、负载 0.08（较空闲）。[[magpie gateway]] 为宿主机原生进程，不计入上表但同样占用内存。

### 风险说明

| 容器 | memory limit | 说明 |
|---|---|---|
| [[tdai-memory-core]] | 0（无限制） | 栈内资源占用最大、OOM 风险最高 |
| [[tdai-memory-hub]] | 0（无限制） | |
| [[tdai-proxy]] | 0（无限制） | |

宿主机仅 **3659 MiB**。

### 建议配额

- core **1536m**、hub **512m**、proxy **512m**（合计约 2.5 GiB，留出宿主与 magpie 余量）。
- **必须写入 `/opt/memhub` 启动脚本**——因为 systemd 会重建容器（见 [[容器化部署与重建语义]]），运行期 `docker update` 无效。

## 服务器 A（无 swap + 大查询）

| 指标 | 值 |
|---|---|
| 总内存 | 1886 MiB（约 1.8 GiB） |
| 已用 | 754 MiB |
| 可用 | 945 MiB |
| buff/cache | 829 MiB |
| Swap | **无** |
| 负载 | 0.10 / 0.05 / 0.04 |
| 主要进程 | [[ClickHouse]] 约 19% 内存、5% CPU |

A 机的风险不是「配额缺失」，而是**物理上限本身低且没有 swap 兜底**：ClickHouse 的大批量分析查询（聚合、join、排序溢出）可以直接吃满剩余内存并触发整机 OOM；同宿主的 [[百度智能云主机安全与管理组件]] 还会额外占用一部分内存，进一步压缩余量。

## 治理对比

| 手段 | B 机 | A 机 |
|---|---|---|
| 硬配额 | 设置容器 `--memory`（建议 1536m/512m/512m） | ClickHouse 侧限制查询内存（如 `max_memory_usage`）与并发 |
| 交换空间 | 有 1.9G swap（可缓解） | 无 swap，只能靠限流 |
| 触发者 | 任一容器 | 大分析查询 |
| 监控重点 | 容器 RSS 与宿主机可用内存 | 查询并发与单查询内存、系统盘水位（48%） |

## 意义

1. 从"无隔离"到"故障域隔离"：单容器 OOM 只杀自己，而不是整机。
2. 内存限制同时是容量规划基线：加新服务前先核对 3659 MiB 的剩余空间。
3. 同一「OOM 风险」概念在两种部署模型下需要两套处方，不能照抄配额建议。
4. A 机「大批量分析建议限流」是原文的显式运维要求，属容量管理而非安全项。
5. 两台主机内存都紧张（1.8G / 3.6G），说明该环境整体处于**低配约束**下运行，任何新增常驻进程都应先评估内存。

## 相关实体

[[tdai-memory-core]]、[[tdai-memory-hub]]、[[tdai-proxy]]、[[Docker]]、[[memhub-stack 服务单元]]、[[ClickHouse]]、[[百度智能云主机安全与管理组件]]、[[服务器 A（instance-47g8z54m）]]、[[腾讯云 CVM VM-0-10-ubuntu]]

## 关系

| 对象 | 关系 |
|---|---|
| [[ClickHouse]] | A 机风险源 |
| [[tdai-memory-core]] | B 机风险源 |
| [[服务器 A（instance-47g8z54m）]] / [[腾讯云 CVM VM-0-10-ubuntu]] | 受影响宿主 |
| [[双机角色分工]] | 解释了为何风险形态不同 |
| [[云厂商托管组件约束]] | A 机内存被不可控 agent 共同占用 |

## 常见话题

资源配额、部署模型、可靠性

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]（B 机容器配额与内存数据）。
- `server-a-clickhouse.md` §1 基础配置（Swap 行）、§4 资源占用、§6 注意事项 2、§7 对比表
