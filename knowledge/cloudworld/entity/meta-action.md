---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/meta-action
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/meta-action-端点族.md
  type: wiki
supersedes: []
tags:
- memhub
- api
- 端点
- 资产
tier: canonical
title: meta-action 端点族
updated_at: '2026-11-18T07:26:22Z'
---

> POST /api/v1/meta/{action} 一族端点（含 asset/list-accessible），信封响应但 data 形状随 action 变化，无效 key 返回 401。

# Definition

[[memhub 云端面板 API]] 中以 `POST /api/v1/meta/{action}` 形式组织的一族端点，代表性成员为 `asset/list-accessible`（列举当前身份可访问的资产）。它以 `action` 名寻址具体能力，所有 action 共用同一外层信封但内层 `data` 各不相同。

# Key Attributes

- **响应形状**：[[信封响应格式]]，但 **`data` 的形状按 action 各自不同**，无法统一解析，见 [[响应形状三分法]]。
- **无效 key 表现**：**HTTP 401 + `code=401`**，与 [[meta-auth-verify 端点]] 的 `200 + valid=false` 构成 [[无效凭据语义分裂]]。
- **身份参数**：body 中放 [[user_key]]，也可用 `user_id` 二选一；**仅带 `x-tdai-user-key` header 会返回 `400 {"code":400,"message":"(root): user_id or user_key is required"}`**（实测 2026-11-12），见 [[身份参数载体约束]]。
- **租户维度**：需同时提供 [[x-tdai-service-id]] 与 [[team_id]]，见 [[租户双维度模型]]；缺 `team_id` 返回 `400 MISSING_TEAM_ID`。
- **分页约束**：`asset/list-accessible` 的 `limit` 上限 100，`data.total` 为总数、`data.items` 为当页，见 [[资产分类与分页模型]]。
- **错误语义**：`404 UNKNOWN_META_ACTION`、`400 MISSING_TEAM_ID`、`400 limit>100`、`401 code=401` 各归其类，见 [[错误码判定表]]。

# Examples

不同「看起来像错误」的返回其实属于不同层：

| 返回 | 真实含义 |
| --- | --- |
| `404 UNKNOWN_META_ACTION` | action 名不存在（路径不对），不是无权限 |
| `400 MISSING_TEAM_ID` | 缺租户维度参数，不是身份无效 |
| `400 limit: Too big: expected number to be <=100` | 分页超出上限，不是服务端 bug |
| `401 {"code":401,...}` | key 无效，不是网络问题 |

# Relationships

- 父级：[[memhub 云端面板 API]]
- 概念：[[响应形状三分法]]、[[信封响应格式]]、[[无效凭据语义分裂]]、[[租户双维度模型]]、[[错误码判定表]]、[[资产分类与分页模型]]
- 身份：[[user_key]]、[[x-tdai-service-id]]、[[team_id]]
- 代码：[[cloud-api-crate]] 的 `list_accessible_assets`
- 证据：[[phase-b 端点证据文档]]
