---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tag-callback-delivery
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tag-callback-delivery.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 数据表
- 回调
tier: canonical
title: tag_callback_delivery
updated_at: '2026-11-18T07:26:22Z'
---

> 回调投递留痕表，用 status/http_status/attempt_count/last_error 判定投递成败，存在一事件两行与 auth_key_ref 建行冻结两个结构性坑。

# Definition

回调投递的留痕表，是判断「打标成功但没回调」第二现场。核心用途：区分「投递失败」与「事件根本没被物化」。

# Key attributes

## 关注列

`status` / `http_status` / `response_code` / `attempt_count` / `last_error` / `target_url`。

## 三种 status

| status | 含义 |
| --- | --- |
| `delivered` | 投递成功 |
| `disabled` | 目标 URL 为空 → **结构性噪音，不是真失败** |
| `config_blocked` | 有 URL 但取不到鉴权值（**含品牌不在白名单**） |

详见 [[回调投递状态机]]。

## 两个结构性坑

1. **一事件两行**：同一事件可能同时有 `delivered` + `disabled` 两行，直接算覆盖率会算错（曾出现 62 行 / 31 事件）。
2. **`auth_key_ref` 建行冻结**：投递行在**建行时**就把 `auth_key_ref` 存死，之后每次重试都用 `NULL` 解析 → 永远拿不到密钥 → 永远 `config_blocked`，改配置不自愈。修法是在 `claimDue` 加租约前按 `event_pk → 品牌 → CallbackSettings.load` 重新解析。

## 快速反证

比 `delivered` 与 `callback_done` 计数：**相等（如 55/55）即投递链路完全正常**，问题在「事件没被物化」，可省掉一整轮查鉴权/URL/网络。

## 查对方库

必须**按时间窗查，不要按 spu 查**（id 拼错会漏看）：

| 环境 | 表 |
| --- | --- |
| prod | `log_mark_result_ai`（**没有** `ety_mark_result_ai`，那是 test 的） |
| test | `ety_mark_result_ai` / `log_mark_result_ai` / `log_mark_result` / `stand_ai_tagging` |

第二信号：表里最后一条写入时间，可立刻判断链路停了多久。见 [[环境隔离与串环境事故]]。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[回调投递状态机]] | status 语义的理论化 |
| [[sdp-tag-api]] | 写入方；对应日志见其关键日志表 |
| [[假成功与严格成功判据]] | HTTP 200 但对方业务失败的假成功在这里落 `last_error` |
| [[tag_task]] | 终态 failed 的任务不会有投递行 |

# Citations

- 04 排障信号手册 §1.2、§1.3、§1.4
