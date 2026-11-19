---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/secret
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/secret.md
  type: wiki
supersedes: []
tags:
- 密钥
- 安全
- 环境变量
tier: canonical
title: Secret
updated_at: '2026-11-18T07:26:22Z'
---

> 存放回调 key 真值的密钥系统，以环境变量方式注入，避免明文进页面与 DB 备份。

# 定义

Secret 是集群侧的密钥管理设施，用来保存回调 key 等敏感真值，并以环境变量形式注入应用。

# 关键属性

- **为什么不用 sys_config**：「参数设置」页面对有权限的人明文可见，且配置进 DB 备份——「今天我就是拿一个 root 账号直接把 key 读出来的」。
- **引用式绑定**：`sys_config` 只存引用名（`tag.callback.auth-ref = zara-key`），真值留在 Secret。

# 关系

- 与 [[sys_config 配置中心]] 共同构成 [[回调配置分层]]。
- 供 [[回调服务]] 使用；运行在 [[部署环境]] 上。

# Citations

- `02-方案选型与权衡.md` §16
