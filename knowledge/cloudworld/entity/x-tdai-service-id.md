---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/x-tdai-service-id
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/x-tdai-service-id.md
  type: wiki
supersedes: []
tags:
- memhub
- 租户
- 身份
tier: canonical
title: x-tdai-service-id
updated_at: '2026-11-18T07:26:22Z'
---

> 租户身份维度标识；与 team_id 是两个独立维度，需同时提供。

# Definition

调用 [[memhub 云端面板 API]] 时表示**租户身份**的维度标识。

# Key Attributes

- **正交维度**：与 [[team_id]]（团队/范围维度）是两个独立维度，两者都要给，缺一不可，见 [[租户双维度模型]]。
- 与 [[user_key]] 的区别：`user_key` 表明「你是谁」，`x-tdai-service-id` 表明「在哪个租户下」，`team_id` 再收窄到团队范围。
- 注意不要与 [[身份参数载体约束]] 混淆：`x-tdai-user-key` header **不能**替代 body 中的 `user_key`，但 `x-tdai-service-id` 属于租户维度，性质不同。

# Relationships

- 概念：[[租户双维度模型]]
- 配对维度：[[team_id]]
- 使用端点：[[meta-action 端点族]]
