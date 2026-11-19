---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/magpie-gateway
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/magpie-gateway.md
  type: wiki
supersedes: []
tags:
- 网关
- 模型路由
- 宿主机进程
- 迁移
tier: canonical
title: magpie gateway
updated_at: '2026-11-18T07:26:22Z'
---

> 宿主机原生运行的模型路由网关，现运行在 B 机（腾讯云 43.142.18.23），监听 docker0 地址 172.17.0.1:3425，供容器访问上游模型供应商；配套 web UI 在 127.0.0.1:3430；2026-11-11 由服务器 A 迁来。

# magpie gateway

## 定义

`magpie-gateway.service`，以**宿主机原生进程**（非容器）运行的模型路由网关，把记忆栈内的模型调用统一转发到 [[上游模型供应商]]。它监听 docker0 网桥地址 `172.17.0.1:3425`，使 [[Docker]] 容器内的 [[tdai-memory-core]] / [[tdai-memory-hub]] / [[tdai-proxy]] 能够访问外部 [[上游模型供应商]]；配套 web UI 在 `127.0.0.1:3430`（仅回环）。

## 关键属性

| 项目 | 值 |
|---|---|
| 监听 | 172.17.0.1:3425（docker0，容器可达） |
| Web UI | 127.0.0.1:3430（magpie web UI；仅回环，见 [[回环绑定与 SSH 隧道访问]]） |
| 部署形态 | 宿主机原生进程（非容器），不计入容器资源统计 |
| 当前宿主 | [[腾讯云 CVM VM-0-10-ubuntu]]（43.142.18.23） |
| 历史宿主 | [[服务器 A（instance-47g8z54m）]]（百度智能云 120.48.25.220），**2026-11-11 迁出** |
| 配置 | `/root/.config/magpie/settings.json`（含 `lanKey`） |

## 迁移沿革

- **迁移前**：magpie 运行在 [[服务器 A（instance-47g8z54m）]] 上，与 [[ClickHouse]] 同宿主。
- **2026-11-11**：magpie 由 A 机迁至 B 机 `43.142.18.23`，A 机自此只剩 ClickHouse 一个业务负载。
- **迁移后语义**：由于容器通过 docker0 访问 gateway，把 gateway 放在**运行容器的那台主机**上才成立；这解释了迁移方向——B 机才是三个容器（[[tdai-memory-core]] / [[tdai-memory-hub]] / [[tdai-proxy]]）的宿主。
- 该迁移是 [[双机角色分工]] 成形的标志性事件。

## 关系

- ← [[服务器 A（instance-47g8z54m）]]：迁移前宿主，与 [[ClickHouse]] 同宿主；2026-11-11 迁出后 A 机只剩 ClickHouse 一个业务负载。
- → [[腾讯云 CVM VM-0-10-ubuntu]]：迁移后宿主。
- ← [[tdai-proxy]]：注入链路上游调用方；[[tdai-memory-core]] / [[tdai-memory-hub]] / [[tdai-proxy]] 均经 docker0 调用 gateway。
- → [[上游模型供应商]]：路由去向（外部依赖）。
- ← [[Docker]]：通过 docker0 网桥可达，是其选择 172.17.0.1 绑定的原因，体现 [[最小暴露面绑定原则]]。
- [[容器化部署与重建语义]]：magpie 本身是宿主进程，不受容器重建影响。
- 资源不纳入 [[资源配额与 OOM 风险]] 的容器配额讨论，但同样消耗宿主机内存。
- [[双机角色分工]]：本次迁移是该分工成形的标志性事件。

## Citations

- `server-a-clickhouse.md` §2 角色与软件（magpie 行）
- `cloud-server.md`（172.17.0.1:3425 / 127.0.0.1:3430）—— 见 [[cloud-server 运维快照]]。
