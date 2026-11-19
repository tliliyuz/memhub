---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/search
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/对方-search-服务.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 回写
- 租户映射
tier: canonical
title: 对方 search 服务
updated_at: '2026-11-18T07:26:22Z'
---

> 回写接收方，接收 recover .../callback/v2，按 brand 映射决定落库租户，只认 ZARA/HM/RL。

# 对方 search 服务

## 定义

打标结果的外部接收方。我方通过 `recover .../callback/v2` POST 结果。

## 关键属性

- 租户存于 `cfg_api_key.tenant_id`，小整数；prod 取值：ZARA 235、hm 186、RL 178、罗意威 238/239/243、Balenciaga/Bottega/McQueen/YSL 207–210，见 [[多租户双编号体系]]。
- **落库租户由 `brand` 决定，不由 key 决定**；V2 回写里品牌映射写死，只认 ZARA/HM/RL，其它走 default 分支——只打日志、返回 success、**不落库**。
- prod 库没有 `ety_mark_result_ai` 表（那是 test 的）。
- 回写的 `track.reason` 是固定枚举（图文互证 / 文字推断 / 图片推断 / 明确不符 / 证据不足），不是模型原文，见 [[证据]]。

## 关系

- 「回调成功」只代表 HTTP 通了；**「落库」是对方的动作**，见 [[重跑动作体系]]。
- 幂等键不含租户/品牌，跨品牌 SPU 重叠时后到者静默跳过，见 [[事件幂等与静默跳过]]。

## 易误解

- 用租户 238 的 Secret 不代表数据会落到 238：`brand=LOEWE` 被映射到 239，实测事故。

## Citations

- `01-术语实义.md` §12、§13 `[D][Z]`。
