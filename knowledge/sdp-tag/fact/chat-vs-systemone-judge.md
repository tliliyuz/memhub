---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/chat-vs-systemone-judge
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/comparisons/chat-源-vs-systemone-源-judge-对比.md
  type: wiki
supersedes: []
tags:
- 评测
- judge
- 对比
tier: canonical
title: chat 源 vs systemone 源（judge 对比）
updated_at: '2026-11-18T07:26:22Z'
---

> 评测台两种 judge 源的对比：systemone（Ark/JEV）稳定 8.9s，chat（ChatJudgeModel）不补问且慢 35×，是端到端不稳定的第一分水岭。

# 对比表

| 维度 | systemone 源（Ark/JEV） | chat 源（[[chat-judge-model]]） |
| --- | --- | --- |
| 补问 | —（默认稳定） | **不补问** |
| 切批依据 | — | 仅按输入 token（12000），不按题数 |
| 最大批次 | — | 87 题 / 单批 304s，p90 248s |
| 连接错误行为 | — | 单批 `IOException` → **取消该 stage 剩余全部批次** |
| 同商品实测耗时 | **8.9s** | 308s / 356s（**35× 慢**） |
| 稳定性 | 好 | 差 |

# 判据与用法

- 「lab 跑出来比 100 件 A/B 不稳定」时的首查项：**先看是哪个 judge 源**，再谈模型好坏。
- chat 的慢是**输出 token 驱动**的，不是「挂住」；不要用超时/线程栈去找死锁。
- 两个源都跑同一商品时，耗时差是最廉价的判别信号。

# 修复状态

- 已修（`afd99bb` + `b963678`）：补问深度 4、chat 题数上限 40、HTTP/1.1 固定 + 4 次重试（1/2/4s 退避）。
- 未修：单批连接错误仍会取消整个 stage。
- 归因修正：「242/469 丢失」根因是**连接重置**（10 线程同一秒 `Connection reset`，改前同样模式），属链路问题。

# Citations

- 04 排障信号手册 §5.6；与 [[评测口径一致性]]、[[lab-bench]] 同域但不重叠
