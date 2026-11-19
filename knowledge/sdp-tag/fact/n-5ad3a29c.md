---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-5ad3a29c
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/回调投递状态机.md
  type: wiki
supersedes: []
tags:
- 回调
- 状态机
- 权限
tier: canonical
title: 回调投递状态机
updated_at: '2026-11-18T07:26:22Z'
---

> delivered / disabled（结构性噪音）/ config_blocked（取不到鉴权值）三态；delivered 与 callback_done 计数相等即证明投递链路完好。

# Definition

回调投递行的状态语义模型，落在 [[tag_callback_delivery]] 表：

| 状态 | 触发条件 | 是否真失败 |
| --- | --- | --- |
| `delivered` | 2xx 且 body.code 通过 | 否 |
| `disabled` | 目标 URL 为空 → **结构性噪音** | **否** |
| `config_blocked` | 有 URL 但取不到鉴权值（**含品牌不在允许列表**） | 是 |

# Significance

- **权限模型视角**：`config_blocked` 的「取不到鉴权值」里混着**品牌白名单**这一类业务规则——日志文案「回调密钥未配置，跳过回写：brand=…」是**误导性描述**。
- **覆盖率会算错**：一个事件可能有两行（`delivered` + `disabled`），曾出现 62 行 / 31 事件。
- **结构性不自愈**：投递行**建行时**把 `auth_key_ref` 存死，重试永远用 `NULL` 解析 → 永远 `config_blocked`；修法是在 `claimDue` 加租约前按 `event_pk → 品牌 → CallbackSettings.load` 重新解析。
- **快速反证**：`delivered` 与 `callback_done` 计数相等（如 55/55）→ 投递链路完好，问题在「事件没被物化」，可省掉一整轮查鉴权/URL/网络。

# Related entities

[[tag_callback_delivery]] · [[sdp-tag-api]] · [[tag_task]]

# Common topics

- **权限模型**：URL 存在性、鉴权密钥、品牌白名单三层判定。
- **可观测性**：状态分布 vs 行数统计的差异（一事件两行）。

# 相关

[[假成功与严格成功判据]]（HTTP 200 但业务失败）· [[环境隔离与串环境事故]]（prod/test 落库表名不同）

# Citations

- 04 排障信号手册 §1.2、§1.4
