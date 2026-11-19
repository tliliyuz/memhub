---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tenanthelper
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tenanthelper.md
  type: wiki
supersedes: []
tags:
- 多租户
- 权限
- 模块
- 租户上下文
tier: canonical
title: TenantHelper
updated_at: '2026-11-18T07:26:22Z'
---

> 租户上下文的唯一权威实现，动态租户已从 Redis 全局键迁移到登录会话的 Token-Session。

# Schema

- **kind**: module
- **职责**：动态租户上下文的读写与清理，是 [[租户上下文隔离]] 模型的唯一权威实现。

# Definition

`TenantHelper.java` 负责动态租户（dynamic tenant）在请求链路中的存取。当前实现把动态租户放在**登录会话（Token-Session）**里，而不是放在以 `userId` 为维度的 Redis 全局键里。

# 关键属性

| 项 | 内容 |
| --- | --- |
| 当前键常量 | `DYNAMIC_TENANT_SESSION_KEY = "dynamicTenant"`（`:37`） |
| 写入点 | `StpUtil.getTokenSession().set(DYNAMIC_TENANT_SESSION_KEY, ...)`（`:150`） |
| 旧键常量 | `LEGACY_DYNAMIC_TENANT_KEY = "global:dynamicTenant:<userId>"`（`:43`），TTL=-1 |
| 旧键状态 | **已不参与读取**，只在注销与重置时由 `clearDynamic()`（`:196`）清理残留，避免旧值误导排查（`:41` 注释） |
| 迁移提交 | `0ed738d fix(tenant): 租户上下文按登录会话隔离`，2026-11-04 17:53 已在 dev |

# 冲突与裁决

**A1：租户上下文按 userId 还是按会话？**

| 说法 | 来源 | 时间 |
| --- | --- | --- |
| `global:dynamicTenant:<userId>`，TTL=-1、按 userId 不按会话 | `[D]` `[Z]` | 2026-10-29 ~ 11-03 |
| 「已合入按登录会话隔离」 | `[C]` | 贴近当前代码 |

**裁决：以代码为准，旧键已失效。** 已用 `git grep` 核对实际行号，`git log` 确认 `0ed738d` 在 dev。

# 已失效结论

- **B13**：「租户上下文按 userId 存」——2026-11-04 `0ed738d` 后改为 Token-Session。
- **排查提示**：现在遇到租户串了，**不要再去找 `global:dynamicTenant:*`**；那是残留清理对象，不是读取源。

# Relationships

- [[租户上下文隔离]] — 实现与模型的关系（A1 裁决的落点）。
- 下游引用：配置与凭据地图 4.3 节的「两个键状态表」（该文档尚未入库）。
- 受影响对象：所有依赖租户上下文做数据隔离的查询与打标链路。

# Citations

- `TenantHelper.java:37, :41, :43, :150, :196`
- `git log`: `0ed738d`（2026-11-04 17:53，dev）
- 源：`06-未决与空白.md` A1、B13、E1
