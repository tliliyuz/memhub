---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/snail-job
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/snail-job.md
  type: wiki
supersedes: []
tags:
- SnailJob
- 调度平台
tier: canonical
title: snail-job
updated_at: '2026-11-18T07:26:22Z'
---

> SnailJob 任务调度平台，控制台挂同域 /snail-job（iframe），内网地址 192.168.31.20:17888。

# snail-job

## Definition

SnailJob 任务调度平台（调度中心），sdp-tag 的定时/异步任务由其下发。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 控制台路径 | 同域 `/snail-job`（**iframe 嵌入**） |
| 内网地址 | `192.168.31.20:17888` |
| nginx 要求 | 必须配 `location /snail-job` |
| token | `${SNAIL_JOB_TOKEN}`（✅ 已是引用） |

## Relationships

- **执行器**：[[sdp-tag-snailjob]]
- **同域挂载**：[[sdp-tag-web]]（前端站点）
- **本地启动必须关闭** → [[local-dev-runtime-baseline]]

## 已知问题

- ⚠️ **本机连上共享环境会真参与调度**，曾抢走 49 条任务租约
- nginx 缺 `location /snail-job` 会导致 iframe 白屏
- 内网地址暴露拓扑（低危）

## Citations

- §2 集群与部署表（SnailJob 控制台行）
- §3.3 本地起服务的标准参数
