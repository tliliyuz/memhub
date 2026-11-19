---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/tencent-cos
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tencent-cos.md
  type: wiki
supersedes: []
tags:
- 对象存储
- 外部系统
- 主图
tier: canonical
title: tencent-cos
updated_at: '2026-11-18T07:26:22Z'
---

> 主图来源之一；公网域名在腾讯云内网解析成 169.254.0.47，落进链路本地黑名单导致主图抓不到。

# Definition

主图来源之一。其公网域名的解析结果与 [[ImageAddressPolicy]] 的地址判定直接冲突。

# Key attributes

- 公网域名在**腾讯云内网**解析成 `169.254.0.47`（就近接入 VIP），落进 `ImageAddressPolicy.isBlocked` 的**链路本地判定** → 主图抓不到。
- 修法：**按主机名整体放行** `TAG_IMAGEFETCH_ALLOWEDHOSTS_0`，**不要放开网段**（`169.254.0.0/16` 含元数据地址）。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[主图抓取放行模型]] | 放行/阻断的完整模型 |
| [[ImageAddressPolicy]] | 执行判定的模块 |
| [[静默失败]] | precheck 失败不记日志，主图问题因此静默 |

# Citations

- 04 排障信号手册 §4.5
