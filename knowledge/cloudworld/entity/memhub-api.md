---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/memhub-api
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/memhub-云端面板-api.md
  type: wiki
supersedes: []
tags:
- memhub
- api
- 平台
tier: canonical
title: memhub 云端面板 API
updated_at: '2026-11-18T07:26:22Z'
---

> memhub 云端服务对外的 HTTP 面板 API 面，承载 instances / auth / asset / user-key 四类端点，响应形状不统一。

# Definition

[[memhub 云端服务]] 对外暴露的面板 HTTP API 面，供客户端读取实例清单、校验凭据、列举可访问资产与换取登录态。它是团队使用 memhub 云端能力的唯一接口入口。

# Key Attributes

- **响应形状不统一**：同一套 API 并存三种形状（裸 JSON / 信封 / 裸扁平 JSON），禁止统一封装解析，见 [[响应形状三分法]]。
- **鉴权语义按端点分裂**：无效 `user_key` 在 [[meta-auth-verify 端点]] 上是 `200 + valid=false`，在 [[meta-action 端点族]] 上是 `401 code=401`，见 [[无效凭据语义分裂]]。
- **身份参数载体**：身份凭据 [[user_key]] 必须放在请求 body，不放 header、不放命令行参数，见 [[身份参数载体约束]]。
- **租户双维度**：需要同时提供 [[x-tdai-service-id]]（租户）与 [[team_id]]（团队），见 [[租户双维度模型]]。
- **分页上限**：资产列表 `limit` 上限 100，见 [[资产分类与分页模型]]。
- **实现归属**：客户端侧封装位于 [[cloud-api-crate]]。

# 端点一览

| 端点 | 形状 | 鉴权行为 |
| --- | --- | --- |
| [[meta-instances 端点]]（`GET /api/v1/meta/instances`） | 裸 JSON | 无鉴权，不涉及 key 校验 |
| [[meta-auth-verify 端点]]（`POST /api/v1/meta/auth/verify`） | 信封，`data` 内嵌 `{valid,user}` | 无效 key 返回 HTTP 200 + `valid=false` |
| [[meta-action 端点族]]（`POST /api/v1/meta/{action}`，如 `asset/list-accessible`） | 信封，`data` 形状随 action 变化 | 无效 key 返回 HTTP 401 + `code=401` |
| [[auth-user-key-login 端点]]（`POST /api/v1/auth/user-key/login`） | 裸扁平 JSON | 未知 key 自动注册（有副作用） |

# Relationships

- 服务端本体：[[memhub 云端服务]]
- 客户端封装：[[cloud-api-crate]]
- 形状与错误语义：[[响应形状三分法]]、[[信封响应格式]]、[[错误码判定表]]
- 来源记录：[[01-接口形态与鉴权坑]]
