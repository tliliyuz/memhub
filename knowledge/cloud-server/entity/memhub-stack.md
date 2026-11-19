---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/memhub-stack
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/memhub-stack-服务单元.md
  type: wiki
supersedes: []
tags:
- systemd
- 部署
- 启动脚本
tier: canonical
title: memhub-stack 服务单元
updated_at: '2026-11-18T07:26:22Z'
---

> systemd oneshot 单元 memhub-stack.service，按 core → hub → proxy 顺序拉起三个容器，每次启动都会重建容器。

# memhub-stack 服务单元

## 定义

`memhub-stack.service`，一个 systemd **oneshot** 单元，负责按固定顺序 `[[tdai-memory-core]] → [[tdai-memory-hub]] → [[tdai-proxy]]` 启动（实为重建）三个 [[Docker]] 容器。

## 关键属性

- 类型：oneshot（执行完即退出，容器由 Docker 持续运行）。
- 顺序：core → hub → proxy，体现依赖方向。
- 资产：`/opt/memhub` 下的启动脚本、`.env`、`.admin-key`（均 600）。
- 同类单元：`magpie-gateway.service`、`nginx.service`、`docker.service`、`fail2ban.service`。
- 操作：`systemctl start memhub-stack`（启动/重建）、`/opt/memhub/stop-all.sh`（停止）、`/opt/memhub/verify.sh`（健康检查）。

## 关系

- 是 [[容器化部署与重建语义]] 的实现载体：**运行期手工改动会在下次重建时丢失**，因此内存 limit 等配置必须写进启动脚本。
- 直接决定 [[Docker 卷数据持久化]] 的边界——只有卷内数据跨重建保留。
- 运维序列见 [[运维操作手册]]。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
