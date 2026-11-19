---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-64ffe1f6
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/重发-重放语义.md
  type: wiki
supersedes: []
tags:
- 回调
- 幂等
- 重放
tier: canonical
title: 重发/重放语义
updated_at: '2026-11-18T07:26:22Z'
---

> 内容相同则重放已有结果并再回调一次，内容变化不拒收而是删旧投递行重排，过期结果置 SUPERSEDED 不重放。

# 定义

对外重复事件的三种走向：

| 情形 | 处理 |
| --- | --- |
| `eventId` 指向不同商品 | **拒绝** |
| 内容相同 | **重放**已有结果并**再回调一次** |
| 内容不同 | **不拒收**：删旧投递行 + merge + 重新排队打标 |

# 放弃的策略

「重复就拒绝丢弃」的旧策略。

# 细节权衡

- 商品哈希已被后续事件替换 → 事件置 `SUPERSEDED`，**不重放旧结果**（避免把过期结果推给对方）。
- **重放节流**：窗口内（默认 60s）已投递的只确认、不重发。
- **重放行整体重建**而非原地重置：`materializeResult` 对 `callback_done` 会直接返回，必须先把事件置 `TAGGED`。

# 关联

- 相关实体：[[回调服务]]、[[TagTaskRunSpec]]
- 相关概念：[[解析后规范化内容摘要]]（判同内容的基础）、[[打标与回调解耦]]、[[活动任务先到先得 + 快照执行]]

# Citations

- `02-方案选型与权衡.md` §15
