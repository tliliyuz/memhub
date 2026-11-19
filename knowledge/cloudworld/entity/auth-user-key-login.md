---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/auth-user-key-login
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/auth-user-key-login-端点.md
  type: wiki
supersedes: []
tags:
- memhub
- api
- 端点
- 鉴权
tier: canonical
title: auth-user-key-login 端点
updated_at: '2026-11-18T07:26:22Z'
---

> POST /api/v1/auth/user-key/login，裸扁平 JSON、不套信封；未知 key 会自动注册，属有副作用的调用。

# Definition

[[memhub 云端面板 API]] 中的登录端点：`POST /api/v1/auth/user-key/login`，用 [[user_key]] 换取登录态。

# Key Attributes

- **响应形状**：**裸扁平 JSON，不套信封**——没有 `code` / `message` / `request_id` / `data` 外壳，与 [[meta-auth-verify 端点]] 形成鲜明对比，见 [[响应形状三分法]]。
- **自动注册**：未知 key 会自动建号，见 [[自动注册语义]]。这是**有副作用**的调用，只能在用户明确同意后触发，不能用在「只是想校验一下 key」的探测场景（该场景应用 [[meta-auth-verify 端点]]）。
- **不可当鉴权探针**：误用它做校验会创建脏账号。

# Relationships

- 父级：[[memhub 云端面板 API]]
- 概念：[[响应形状三分法]]、[[自动注册语义]]、[[凭据安全处理实践]]
- 对比：[[meta-auth-verify 端点]]（信封 + 只读校验，无副作用）
- 实现：[[cloud-api-crate]]
