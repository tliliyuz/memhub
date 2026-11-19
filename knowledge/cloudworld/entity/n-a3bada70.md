---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloudworld/entity/n-a3bada70
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/系统凭据库.md
  type: wiki
supersedes: []
tags:
- 凭据
- 安全
- windows
tier: canonical
title: 系统凭据库
updated_at: '2026-11-18T07:26:22Z'
---

> Windows Credential Manager（service 为 `cloud-world`），是 `user_key` 与 `relay-token` 唯一的持久化存放位置；运行期解析，更换凭据只需界面重新登录，与打包和重编无关。

# 定义

系统凭据库是操作系统提供的外部凭据存储。本应用在 Windows 上使用 Windows Credential Manager，service 固定为 `cloud-world`，通过 account 命名区分具体条目：

| account | 内容 |
| --- | --- |
| `<profile>:panel-user-key` | 用户密钥（`user_key`） |
| `<profile>:relay-token` | relay 本地令牌 |

`panel-user-key` 与 `relay-token` 分别对应 [[凭据模块]] 中的常量 `USER_KEY_SUFFIX`、`RELAY_TOKEN_SUFFIX`；`<profile>:` 前缀是 [[多 profile 隔离]] 的实现手段，由 [[profile]] 提供。

因为凭据在运行期解析、不进二进制，更换凭据只需在界面重新登录，无需重新打包或重编 exe，凭据也不进安装包。它是 [[凭据边界]] 中密钥**唯一**的持久化位置，也是 [[key 生命周期数据流]] 中唯一的持久化节点。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 类型 | `external_system`（外部系统） |
| 存储内容 | `user_key`、`relay-token` |
| 服务名 | `cloud-world` |
| account 命名 | `<profile>:panel-user-key`、`<profile>:relay-token` |
| 解析时机 | 运行期 |
| 更换方式 | 界面重新登录 |
| 是否需重编 exe | 不用 |
| 是否进安装包 | 不进 |
| 加密 | 加密存储，密钥不以明文落盘 |
| 可查询状态 | 凭据存在与否可查询，桌面端后端据此暴露 `has_user_key` |

# 关系

- 与 [[运行期配置文件 config.toml]]（[[配置文件 config.toml]]）并列，构成 [[运行期配置与凭据分离]] 的「凭据」一侧；两者也是互斥边界：敏感内容只进本库，非敏感配置只进配置文件。
- 属于 [[打包分层模型]] 中免重编的层次。
- 由 [[凭据模块]] 独占读写，常量定义与 account 命名规则在该模块内对齐。
- account 前缀 `<profile>:` 由 [[profile]] 提供，实现多档案隔离（[[多 profile 隔离]]）。
- 凭据存在与否是可被查询的状态：桌面端后端据此对外暴露 `has_user_key`，状态被 [[桌面登录入参]] 读取，并驱动 [[桌面登录门禁]] 的 `prefill` 分支与判定。
- 缺失凭据时，连接请求被拒绝且不产生任何文件——这是「凭据是功能硬门槛」的直接体现。
- 与 [[配置文件 config.toml]] 的明文属性对比：本库加密存储，密钥不以明文落盘。

# Citations

- `crates/desktop/src-tauri/src/lib.rs`
- `06-凭据边界.md`
