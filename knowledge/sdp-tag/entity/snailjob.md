---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/snailjob
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/snailjob.md
  type: wiki
supersedes: []
tags:
- 调度
- 外部系统
- 配置
tier: canonical
title: snailjob
updated_at: '2026-11-18T07:26:22Z'
---

> 调度平台客户端，server.*（gRPC 17888）与 openapi.*（HTTP 8800）是两个独立端点，只配前者会导致无限重试且隐藏堆栈。

# Definition

调度平台客户端，负责初始化并驱动定时任务（如 `ImageTransferJobInitializer`）。它的故障表现是「注册和心跳都正常，但任务初始化无限重试」。

# Key attributes

## 两个独立端点

| 配置 | 协议 | 端口 |
| --- | --- | --- |
| `snail-job.server.*` | gRPC | 17888 |
| `snail-job.openapi.*` | HTTP | 8800 |

只配 `server.*` 时：客户端注册与心跳正常，但 `ImageTransferJobInitializer` **无限重试**，且只打 `errorType=IORuntimeException`（60s 退避，**没有堆栈，消息被故意隐藏**）。

## 端口拼接陷阱

`snail-job.port: 2${server.port}` 是**字符串拼接** `[D]`：换端口会拼出 `218123` 越界导致启动失败，需同时传 `--snail-job.port=`。

## 调度库

`sj_job_task.create_dt` / `update_dt`（**不是** `create_time`）。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[配置生效与三源优先级]] | 端点配置分离的同类问题 |
| [[sdp-tag-api]] | 客户端宿主 |
| [[静默失败]] | 「没有堆栈的错误」是静默失败的一种形态 |

# Citations

- 04 排障信号手册 §4.11、§4.12、§6
