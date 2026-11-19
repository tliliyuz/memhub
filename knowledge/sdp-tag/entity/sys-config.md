---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/sys-config
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/sys-config-配置中心.md
  type: wiki
supersedes: []
tags:
- 配置
- 缓存
- 运营
tier: canonical
title: sys_config 配置中心
updated_at: '2026-11-18T07:26:22Z'
---

> 存放运营可改配置（如回调 URL、header 名）的配置中心，按租户 Redis hash 缓存。

# 定义

`sys_config` 是运营可在线修改的配置中心，用于存放回调 URL、header 名等需要即时生效的配置项。

# 关键属性

- **缓存模型**：按租户 Redis hash 缓存，key 形如 `<tenantId>:sys_config`。
- **⚠️ 改库不生效**：直接在 MySQL 里改 `sys_config` **不会生效**，必须先把该字段从 Redis hash 里 `HDEL`。
- **不能放密钥**：「参数设置」页面对有权限的人**明文可见**，且会进 DB 备份；DB 暴露面远大于 Secret。
- **只存引用名**：如 `tag.callback.auth-ref = zara-key`，真值由 [[Secret]] 挂成环境变量。

# 关系

- 被 [[回调服务]] 读取，与 [[Secret]] 组成 [[回调配置分层]]。

# Citations

- `02-方案选型与权衡.md` §16
