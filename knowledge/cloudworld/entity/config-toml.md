---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/config-toml
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/配置文件-config-toml.md
  type: wiki
supersedes: []
tags:
- 配置
- 文件
- 安全
tier: canonical
title: 配置文件 config.toml
updated_at: '2026-11-18T07:26:22Z'
---

> %APPDATA%\cloud-world\config.toml，只存 profile 等非敏感配置，不含任何密钥，是凭据边界的负向基线。

# 配置文件 config.toml

## Definition

配置文件位于 `%APPDATA%\cloud-world\config.toml`，存放应用的非敏感配置（如 [[profile]] 列表等），**不含任何密钥**。

## Key Attributes

- **kind**: other
- 明文存储：容易进备份、进 git、进截图——这正是密钥不能放这里的原因。
- 是 [[凭据边界]] 的**负向定义**：凡敏感项（`user_key`、relay token）只能落在 [[系统凭据库]]。
- `config_exists` 与 profile 列表是 [[桌面登录门禁]] 的判定输入之一。

## Relationships

- 与 [[系统凭据库]] 构成职责互斥：明文配置 vs 加密凭据。
- 由 [[桌面登录门禁]] 读取（`env.config_exists`、`env.profiles`）。
- 定义 [[profile]] 的持久化位置（profile 元数据在此，profile 对应密钥在凭据库）。
- 约束见 [[密钥不落盘原则]]。
