---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/n-bf32c1bf
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/资产服务.md
  type: wiki
supersedes: []
tags:
- 服务端模块
- 资产
- 权限校验
tier: canonical
title: 资产服务
updated_at: '2026-11-18T07:26:22Z'
---

> 服务端资产模块（crates/service/src/assets.rs），提供可访问资产列表与默认资产读写，并承担成员关系、归属与可见性校验。

# 定义

资产服务是服务端的资产读写模块，实现位于 `crates/service/src/assets.rs`。它提供可访问资产查询（`asset/list-accessible`）与账号级默认资产读写（`user-session-default/set`），并在写入时完成权限相关校验。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 代码位置 | `crates/service/src/assets.rs` |
| 主要接口 | `asset/list-accessible`（可访问资产列表）、`user-session-default/set`（写入账号默认资产） |
| 校验职责 | 成员关系、agent 归属、可见性 |
| 校验位置 | 全部在服务端完成，客户端不做本地猜测 |

# 关系

- 是 [[账号级默认会话资产记录]] 的读写与校验归属模块。
- 与 [[会话初始化服务]] 分工：本模块管资产读写/校验，会话初始化服务管优先级解析。
- 校验原则见 [[服务端权威校验]]：写失败时客户端原样透传服务端错误，不自行推断原因。
- 查询结果供 [[交互式资产选择表单]] 与 [[cloud-world CLI]]（`asset default`）等消费。

# 权限模型

| 校验项 | 说明 |
| --- | --- |
| 成员关系 | 调用者是否为目标 team 成员 |
| agent 归属 | 目标 agent 是否属于该 team / 账号 |
| 可见性 | 目标资产是否对调用者可见 |

# Citations

- `crates/service/src/assets.rs`（`asset/list-accessible` 与默认资产读写）
