---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/phase-b
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/phase-b-端点证据文档.md
  type: wiki
supersedes: []
tags:
- memhub
- 证据
- 文档
tier: canonical
title: phase-b 端点证据文档
updated_at: '2026-11-18T07:26:22Z'
---

> docs/evidence/2026-11-11-phase-b-endpoints.md，记录三端点实际响应形状与 request_id 的实测证据。

# Definition

仓库内的实测证据文档 `docs/evidence/2026-11-11-phase-b-endpoints.md`，记录了 [[memhub 云端面板 API]] 三个端点（[[meta-auth-verify 端点]]、[[meta-action 端点族]]、[[auth-user-key-login 端点]]）的实际响应形状与 `request_id` 取值。

# Key Attributes

- **作用**：为 [[响应形状三分法]] 与 [[信封响应格式]] 提供可复核的一手观测数据（真实报文而非推测）。
- **可追溯定位**：是「结论—代码—证据」三向链条中的「证据」一环，与 [[cloud-api-crate]] 的代码依据互补。
- **覆盖范围**：端点形状与 `request_id`；不含服务端实现细节。

# Relationships

- 结论页：[[01-接口形态与鉴权坑]]
- 代码页：[[cloud-api-crate]]
- 被证实的端点：[[meta-auth-verify 端点]]、[[meta-action 端点族]]、[[auth-user-key-login 端点]]
