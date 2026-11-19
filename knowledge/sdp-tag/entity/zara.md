---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/zara
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/zara-租户.md
  type: wiki
supersedes: []
tags:
- 租户
- 回调
- brand
tier: canonical
title: ZARA 租户
updated_at: '2026-11-18T07:26:22Z'
---

> tenant 235，按 brand 路由回调 key 的目标租户，未知品牌必须跳过而不能回落到它。

# 定义

ZARA 是系统的目标租户（tenant 235），其商品数据与回调凭据按 `brand` 路由。

# 关键属性

- **按 brand 取 key**：载荷里的 `brand` 原样带过来匹配回调 key。
- **未知品牌必须跳过**并打 ERROR：回落默认 key 等于把别家数据写进 ZARA 的 tenant 235，「这比不回写更糟」。

# 关系

- 是 [[按 brand 路由 key]] 的目标租户；配置经 [[回调配置分层]] 管理。
- 相关样本见 [[评估样本集]]（Zara 79 / 76）。

# Citations

- `02-方案选型与权衡.md` §17、§28
