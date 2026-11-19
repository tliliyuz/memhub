---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/profile-isolation
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/other/profile-isolation.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: profile-isolation
updated_at: '2026-11-18T07:26:22Z'
---

# 多 profile 隔离

## Definition

多 profile 隔离是指：不同 [[profile]] 的密钥在 [[系统凭据库]] 中以 account 前缀 `<profile>:` 区分（如 `<profile>:panel-user-key`、`<profile>:relay-token`），因此多个 profile 之间天然隔离，**不需要引入额外的作用域（scope）概念**。

## Significance

- 用命名约定替代一层抽象：减少概念数量，降低实现与理解成本。
- 隔离同时存在于两个平面：[[配置文件 config.toml]] 中的 profile 元数据、凭据库中带前缀的凭据条目。

## Related Entities

- [[系统凭据库]] — 前缀在前缀在 account 上实现隔离。
- [[凭据模块]] — 定义 suffix 常量与 account 拼接规则。
- [[profile]] — 前缀的取值来源。
- [[桌面登录门禁]] — `prefill` 逻辑依赖「profile 存在」与「key 存在」两个独立状态。

## Common Topics

- **权限模型**：每个 profile 的密钥独立条目，互不覆盖。
- **数据流**：读写路径一致地携带 `<profile>:` 前缀。
