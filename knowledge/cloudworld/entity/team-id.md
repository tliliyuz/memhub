---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/team-id
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/team-id.md
  type: wiki
supersedes: []
tags:
- memhub
- 租户
- 身份
tier: canonical
title: team_id
updated_at: '2026-11-18T07:26:22Z'
---

> 团队/范围维度标识，缺失时返回 400 MISSING_TEAM_ID。

# Definition

调用 [[memhub 云端面板 API]] 时表示**团队/范围**的维度标识。

# Key Attributes

- **缺失后果**：返回 `400 MISSING_TEAM_ID`，这是参数缺失而非身份无效，见 [[错误码判定表]]。
- **正交维度**：与 [[x-tdai-service-id]]（租户维度）并行，两者需同时提供，见 [[租户双维度模型]]。
- **不影响鉴权结论**：`MISSING_TEAM_ID` 不等于 [[user_key]] 无效。

# Relationships

- 概念：[[租户双维度模型]]、[[错误码判定表]]
- 配对维度：[[x-tdai-service-id]]
- 使用端点：[[meta-action 端点族]]
