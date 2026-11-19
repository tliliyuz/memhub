---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/profile
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/other/profile.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: profile
updated_at: '2026-11-18T07:26:22Z'
---

# profile

## Definition

profile（配置档案）是用户在应用内定义的一套连接配置标识。其非敏感元数据保存在 [[配置文件 config.toml]] 中，对应的密钥则以 `<profile>:` 前缀作为 account 写入 [[系统凭据库]]。

## Key Attributes

- **kind**: other
- 一个 profile 对应凭据库中的多个条目：`<profile>:panel-user-key`、`<profile>:relay-token`。
- 因此多 profile **天然隔离**，不需要额外作用域概念（见 [[多 profile 隔离]]）。
- profile 的存在与密钥的存在是**两个独立状态**：有 profile 但 `has_user_key === false` 时会触发 [[桌面登录门禁]] 的 `prefill` 分支，只补 key、不重建 profile。

## Relationships

- 元数据存于 [[配置文件 config.toml]]，密钥存于 [[系统凭据库]]。
- 前缀规则由 [[凭据模块]] 定义的 suffix 常量拼接而成。
- 影响 [[桌面登录门禁]] 的 `env.profiles.length` 判定。
