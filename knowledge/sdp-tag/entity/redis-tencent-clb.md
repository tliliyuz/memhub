---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/redis-tencent-clb
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/redis-tencent-clb.md
  type: wiki
supersedes: []
tags:
- 腾讯云
- Redis
- 凭据风险
tier: canonical
title: redis-tencent-clb
updated_at: '2026-11-18T07:26:22Z'
---

> 腾讯云 Redis 实例 lb-b832h3rd-…sh-tencentclb.cloud:6379，密码明文在 application-dev.yml:112，maxmemory=0 + noeviction。

# redis-tencent-clb

## Definition

sdp-tag 使用的 Redis 实例，**位于腾讯云而非阿里云**，与 RDS 分属两家云。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 地址 | `lb-b832h3rd-wix6tr3kcabylfnz.clb.sh-tencentclb.cloud:6379` |
| 密码 | `application-dev.yml:112` **明文** `ni7gzrJj…` |
| db（dev） | 6 |
| db（prod） | 3 |
| 内存策略 | `maxmemory=0` + `noeviction` |

## Relationships

- **网络**：跨云 → 必须进 `nonProxyHosts`（`*.sh-tencentclb.cloud`）→ [[proxy-routing-policy]]
- **租户键**：承载历史残留键 `global:dynamicTenant:<userId>` → [[tenant-context]]
- **凭据风险**：[[credential-leak-and-rotation]]
- **消费方**：[[sdp-tag-backend]]

## 已知问题

- `maxmemory=0` + `noeviction` → **不限内存，靠整机扛**，有 OOM 风险
- 密码明文落库
- ⚠️ `[Z]` 用户曾误以为它与 RDS 同厂（都是阿里云），实际在腾讯云——这直接影响代理绕行配置
- `global:dynamicTenant:<userId>` 是**历史残留、已不参与读取**，遇到串租户不要去删它

## Citations

- §4.3 Redis
- §6 代理与网络（nonProxyHosts）
