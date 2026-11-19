---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-cec8235d
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/资产分类与分页模型.md
  type: wiki
supersedes: []
tags:
- memhub
- 资产
- 分页
tier: canonical
title: 资产分类与分页模型
updated_at: '2026-11-18T07:26:22Z'
---

> 资产列表以 data.total 表总数、data.items 表当页，limit 上限 100；讨论「资产」前须先声明类别。

# Definition

[[meta-action 端点族]] 的 `asset/list-accessible` 返回可访问的**资产**集合，采用分页结构：

- `data.total`：符合条件的资产总数。
- `data.items`：当前页的资产条目。
- `limit`：每页条数，**上限 100**，超出返回 `400 limit: Too big: expected number to be <=100`（见 [[错误码判定表]]）。

# 资产分类

资产并非只有 wiki，实测某用户 85 项资产的构成为：

| 类别 | 数量 |
| --- | --- |
| `skill` | 78 |
| `llm_wiki` | 4 |
| `chat_memory` | 3 |
| **合计** | **85** |

`skill` / `llm_wiki` / `chat_memory` 仅作为资产分类的**取值**，不单独成页；讨论「资产」数量或能力覆盖时，必须先声明是哪一类。

# Significance

- **避免口径混淆**：说「用户有 85 项资产」与「用户有 4 篇 wiki」是不同结论，混谈会得出错误的产品判断。
- **分页必须遍历**：`items` 只是当页，统计总量应读 `total` 或循环翻页；`limit` 盲目设大（如 500）会直接 400。
- **可见性受租户维度影响**：结果由 [[x-tdai-service-id]] 与 [[team_id]] 共同收窄，见 [[租户双维度模型]]。

# Related Entities

- [[meta-action 端点族]]、[[cloud-api-crate]]（`list_accessible_assets` 的 limit 校验）

# Common Topics

- 数据流：`total` / `items` 的语义分离，分页游标与总量统计。
- 权限模型：可访问资产的判定依赖身份 + 租户 + 团队三重上下文。
