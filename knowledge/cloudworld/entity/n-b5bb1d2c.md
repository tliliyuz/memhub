---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/n-b5bb1d2c
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/桌面登录入参.md
  type: wiki
supersedes: []
tags:
- 桌面端
- tauri
- rust
- 安全
- 内存
tier: canonical
title: 桌面登录入参
updated_at: '2026-11-18T07:26:22Z'
---

> crates/desktop/src-tauri/src/lib.rs 中的登录命令入参结构体，刻意不实现 Debug/Clone，key 用后 zeroize()，对外暴露 has_user_key。

# 桌面登录入参

## Definition

桌面登录入参是 `crates/desktop/src-tauri/src/lib.rs` 中桌面登录命令的入参结构体，负责在单次调用内承载 `user_key` 并交给 [[凭据模块]] 写入 [[系统凭据库]]，同时对外暴露凭据存在性状态。

## Key Attributes

- **kind**: module
- **刻意不实现 `Debug`**：`{:?}` 会把 key 打进日志。
- **刻意不实现 `Clone`**：避免内存中多留一份密钥拷贝。
- key 只搬进**一个**缓冲区，用后 `zeroize()` 原地清零。
- 对外暴露 `has_user_key`，供前端 [[桌面登录门禁]] 判断是否走 `prefill` 分支。

## Relationships

- 是 [[密钥不落盘原则]] 在**内存侧**的落点：不打印、不复制、用后清零。
- `has_user_key` 驱动 [[桌面登录门禁]] 的 `prefill` 逻辑。
- 写入目标为 [[系统凭据库]]，写入实现位于 [[凭据模块]]。
- 处于 [[key 生命周期数据流]] 的「入参 → 内存缓冲 → 凭据库」环节。
