---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/cloud-api-crate
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-api-crate.md
  type: wiki
supersedes: []
tags:
- memhub
- rust
- 代码
- 模块
tier: canonical
title: cloud-api-crate
updated_at: '2026-11-18T07:26:22Z'
---

> 封装 memhub 面板 API 的 Rust crate；lib.rs 注释规定三种响应形状不得统一处理，client.rs 实现 verify_user_key 与 list_accessible_assets。

# Definition

`crates/cloud-api` —— 客户端侧封装 [[memhub 云端面板 API]] 的 Rust crate，负责按端点各自的形状发请求、解析响应并校验参数。

# Key Attributes

| 文件 | 角色 |
| --- | --- |
| `crates/cloud-api/src/lib.rs` | 模块顶层注释**明确规定三种响应形状不得统一处理**，是 [[响应形状三分法]] 的权威出处。 |
| `crates/cloud-api/src/client.rs` | 实现 `verify_user_key`（对应 [[meta-auth-verify 端点]]）与 `list_accessible_assets`（对应 [[meta-action 端点族]]），包含鉴权头处理与 `limit` 校验。 |

- **鉴权头与 body 的取舍**：`client.rs` 中的实现是 [[身份参数载体约束]] 的代码依据——身份字段进 body，header 不满足身份要求。
- **参数校验**：`list_accessible_assets` 对 `limit` 做上限校验（100），是 [[错误码判定表]] 中 limit 一行的代码侧体现。

# Relationships

- 所封装的接口面：[[memhub 云端面板 API]]
- 相关端点：[[meta-auth-verify 端点]]（`verify_user_key`）、[[meta-action 端点族]]（`list_accessible_assets`）、[[meta-instances 端点]]
- 概念依据：[[响应形状三分法]]、[[信封响应格式]]、[[身份参数载体约束]]
- 证据文档：[[phase-b 端点证据文档]]
- 来源：[[01-接口形态与鉴权坑]]（结论—代码—证据三向可追溯中的「代码」一环）
