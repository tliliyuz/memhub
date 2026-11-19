---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/dynamictenant
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/租户上下文与-dynamictenant.md
  type: wiki
supersedes: []
tags:
- 租户
- 权限模型
- 会话
tier: canonical
title: 租户上下文与 dynamicTenant
updated_at: '2026-11-18T07:26:22Z'
---

> 当前按 token-session 存 dynamicTenant，切换只影响本会话；Redis global:dynamicTenant:<userId> 是历史残留、已不参与读取。

# 租户上下文与 dynamicTenant

## Definition

sdp-tag 中标识「当前请求属于哪个租户」的上下文机制。

## Significance

历史上有过两套存储位置，**只有一套仍在生效**。搞不清就会在排障时删错键、改错地方，且不解决串租户问题。

## 两个键要分清

| 键 | 状态 | 说明 |
| --- | --- | --- |
| `global:dynamicTenant:<userId>`（Redis） | **历史残留，已不参与读取** | 2026-11-04 `0ed738d` 之前按 userId 存，TTL=-1，**会串租户** |
| Token-Session 里的 `dynamicTenant` | ✅ **当前生效** | 一个登录 token 一份，切换**只影响本会话** |

## 排障指引

⚠️ **现在遇到租户串了，不要再去找 `global:dynamicTenant:*`**——那是历史残留，删了不解决。

## Related Entities

- [[redis-tencent-clb]] — 历史残留键所在
- [[sdp-tag-backend]] — 上下文维护方
- [[api-key-authorization]] — 对外 Key 也按 scope 授权

## Common Topics

- 权限模型
- 系统架构 / 会话管理

## Citations

- §4.3 Redis（租户相关两个键）
