---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-41facd20
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/租户双维度模型.md
  type: wiki
supersedes: []
tags:
- memhub
- 租户
- 权限模型
tier: canonical
title: 租户双维度模型
updated_at: '2026-11-18T07:26:22Z'
---

> x-tdai-service-id（租户）与 team_id（团队）是正交的两个维度，缺一不可。

# Definition

[[memhub 云端面板 API]] 的请求范围由**两个正交维度**共同确定：

| 维度 | 标识 | 含义 |
| --- | --- | --- |
| 租户 | [[x-tdai-service-id]] | 处于哪个租户/服务空间 |
| 团队 | [[team_id]] | 租户内的团队/范围 |

# Significance

- **必须同时提供**：`x-tdai-service-id` 是租户身份，`team_id` 是另一维，两者都要给。
- **缺失是可区分的错误**：缺 `team_id` 返回 `400 MISSING_TEAM_ID`，代表「参数不全」；而 `401 code=401` 才代表 key 无效，见 [[错误码判定表]]。
- **与身份凭据正交**：[[user_key]] 回答「你是谁」，本模型回答「在哪个租户/团队的范围内」。三者组合才构成完整的请求上下文，见 [[身份参数载体约束]]。
- **对资产可见性的影响**：[[meta-action 端点族]] 的 `asset/list-accessible` 结果受这两个维度共同收窄，见 [[资产分类与分页模型]]。

# Related Entities

- [[x-tdai-service-id]]、[[team_id]]、[[user_key]]、[[meta-action 端点族]]

# Common Topics

- 权限模型：租户隔离 + 团队范围的两级作用域。
- 系统架构：多维上下文参数在网关/客户端需统一注入，避免某维漏传。
