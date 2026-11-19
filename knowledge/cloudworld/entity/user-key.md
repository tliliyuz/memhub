---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/user-key
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/user-key.md
  type: wiki
supersedes: []
tags:
- memhub
- 凭据
- 身份
tier: canonical
title: user_key
updated_at: '2026-11-18T07:26:22Z'
---

> 调用方身份凭据，必须置于请求 body（非 header、非命令行参数）。

# Definition

调用 [[memhub 云端面板 API]] 时代表调用方身份的一串凭据（key）。

# Key Attributes

- **载体约束**：必须放在请求 **body** 中，见 [[身份参数载体约束]]。
  - [[meta-auth-verify 端点]] 从 body 读 `user_key`。
  - [[meta-action 端点族]] 的 body 接受 `user_key` 或 `user_id` 二选一。
- **header 无效**：仅带 `x-tdai-user-key` header 而 body 无身份字段，会返回 `400 {"code":400,"message":"(root): user_id or user_key is required"}`（实测 2026-11-12）。
- **命令行泄漏风险**：不要作为命令行参数传递（进程列表可见），见 [[凭据安全处理实践]]。
- **校验与副作用分离**：校验用 [[meta-auth-verify 端点]]（只读，返回 `valid` 布尔值）；[[auth-user-key-login 端点]] 会对未知 key 自动注册，见 [[自动注册语义]]。
- **无效时的表现**：`valid=false`（verify）或 `401 code=401`（meta action），见 [[无效凭据语义分裂]]。

# Relationships

- 校验端点：[[meta-auth-verify 端点]]
- 登录端点：[[auth-user-key-login 端点]]
- 与 [[user_id]] 可二选一（meta action 族）
- 概念：[[身份参数载体约束]]、[[凭据安全处理实践]]
