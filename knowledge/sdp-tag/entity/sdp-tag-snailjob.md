---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: sdp-tag/entity/sdp-tag-snailjob
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/sdp-tag-snailjob.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 任务执行器
- snailjob
tier: canonical
title: sdp-tag-snailjob
updated_at: '2026-11-18T07:26:22Z'
---

> sdp-tag 的任务执行器镜像，与 SnailJob 调度中心对接；本机启动时不关会真参与调度，曾抢走 49 条任务租约。

# sdp-tag-snailjob

## Definition

sdp-tag 的任务执行器服务镜像，向 [[snail-job]] 调度中心注册并领取定时任务。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 镜像名 | `sdp-tag-snailjob`（[[acr-registry]]） |
| 调度中心内网地址 | `192.168.31.20:17888` |
| token 注入 | `${SNAIL_JOB_TOKEN}`（✅ 已是引用，非明文） |
| 端口配置 | `snail-job.port: 2${server.port}`（**字符串拼接**） |

## Relationships

- **调度方**：[[snail-job]]
- **部署于** [[tke-cluster-cls-62409zrl]]
- **本地启动必须关闭** → [[local-dev-runtime-baseline]]

## 已知问题

- ⚠️ **本机启动不关 `--snail-job.enabled=false` 会真参与共享环境调度**——曾抢走 49 条任务租约
- `snail-job.port: 2${server.port}` 是**字符串拼接**：换端口会拼出 `218123` 越界，需同时传 `--snail-job.port=`
- 内网地址暴露拓扑（低危，见 §10）

## Citations

- §2 集群与部署表
- §3.3 本地起服务的标准参数
- §10 凭据风险汇总（低危行）
