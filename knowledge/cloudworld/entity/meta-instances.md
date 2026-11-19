---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/meta-instances
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/meta-instances-端点.md
  type: wiki
supersedes: []
tags:
- memhub
- api
- 端点
tier: canonical
title: meta-instances 端点
updated_at: '2026-11-18T07:26:22Z'
---

> GET /api/v1/meta/instances，四种端点中唯一的裸 JSON 端点，无鉴权、不涉及 key 校验。

# Definition

[[memhub 云端面板 API]] 中的实例清单端点：`GET /api/v1/meta/instances`。返回可直接解析的裸 JSON，用于获取实例列表。

# Key Attributes

- **响应形状**：裸 JSON，不套 [[信封响应格式]]，没有 `code` / `message` / `request_id` / `data` 外壳。
- **鉴权**：无鉴权，不涉及 [[user_key]] 校验，因此不存在 [[无效凭据语义分裂]] 问题。
- **无 body 身份参数**：不需要 [[身份参数载体约束]] 所涉的 body 字段。
- **解析要求**：客户端必须为它保留独立的解析路径，不能与其他端点共用信封解析逻辑（见 [[响应形状三分法]]）。

# Relationships

- 父级：[[memhub 云端面板 API]]
- 形状归类：[[响应形状三分法]] 中的「裸 JSON」一支
- 同类对比：[[auth-user-key-login 端点]]（裸扁平 JSON，但带身份语义）
- 实现：[[cloud-api-crate]]
