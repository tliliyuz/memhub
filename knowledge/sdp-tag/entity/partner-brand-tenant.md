---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/partner-brand-tenant
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/partner-brand-tenant.md
  type: wiki
supersedes: []
tags:
- 回调
- 租户
- 凭据风险
tier: canonical
title: partner-brand-tenant
updated_at: '2026-11-18T07:26:22Z'
---

> 对方品牌租户（ZARA / 罗意威等），作为回调接收方；其 cfg_api_key 被 root 直读、token 明文外流。

# partner-brand-tenant

## Definition

sdp-tag 的**业务合作方品牌租户**，打标完成后由 sdp-tag 主动回调其接口交付结果。已知品牌标识含英文字面量 `zara-new` 与**中文「罗意威」**。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 回调认证头 | `X-API-Key` 或 `Authorization: Bearer`（二者皆可） |
| 品牌标识样例 | `LOEWE`、`罗意威`、`zara-new` |
| 凭据 | `cfg_api_key`（存于对方库）、品牌 token |
| 回调地址（test） | `http://yxzhtest3.applesay.cn/api/recover/tagging/ai/callback/v2` |
| 回调地址（prod） | `http://search3.moechat.cn/api/recover/tagging/ai/callback/v2` |

## Relationships

- **回调方**：[[sdp-tag-backend]]，机制见 [[callback-and-brand-allowlist]]
- **命名坑**：[[env-var-relaxed-binding]]（`CALLBACK_AUTH_VALUE`、`CALLBACK_BRANDS`）
- **凭据同源**：[[aliyun-rds-instances]] 上被 root 直读

## 已知问题

- 🔴 **`cfg_api_key` 用对方 root 账号直接 SELECT 读出**，对方大概率不知情；prod ZARA key 有真实线上写权限
- 🟠 罗意威 token 直接贴进会话明文
- 🟠 `source.zara.token`（老服务 admin-api 会话凭证）已随 zip 外流
- ⚠️ **品牌白名单只写 `LOEWE` 会漏掉中文「罗意威」**——回调被跳过
- ⚠️ **`zara-new` 只在 yml 里有，删 env 会让它立刻 `config_blocked`**
- ⚠️ 对方同时认 `X-API-Key` 和 `Authorization: Bearer`，但 `X-ApiKey` / `apikey` / `X-Token` 一律 `未认证`；key 放 query 也不认

## Citations

- §0 P0-3
- §3.2 MQ 与回调表
- §10 凭据风险汇总
