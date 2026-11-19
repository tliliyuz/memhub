---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/chat-judge-model
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/chat-judge-model.md
  type: wiki
supersedes: []
tags:
- 评测
- judge
- 模块
tier: canonical
title: chat-judge-model
updated_at: '2026-11-18T07:26:22Z'
---

> 评测台 chat 源 judge 实现：不补问、按输入 token 切批、连接错误 fail fast 取消整个 stage，比 systemone 慢 35×。

# Definition

lab 评测台的一种 judge 实现（`ChatJudgeModel`）。它的稳定性问题是「lab 端到端不稳定」最容易被误判为「模型不行」的来源。

# Key attributes

## 与 systemone 的差异

| 项 | chat（`ChatJudgeModel`） | systemone（Ark/JEV） |
| --- | --- | --- |
| 补问 | **不补问** | — |
| 稳定性 | 差 | 好 |
| 同商品实测 | 308s / 356s | **8.9s** |

慢是**输出 token 驱动**的，不是挂住。详见 [[chat 源 vs systemone 源（judge 对比）]]。

## 丢答案的三个来源

1. **成功批次里缺 ID**：37/145 的丢失发生在返回 200 的批次里，模型返回 JSON 但漏了题号，且不补问。
2. **批次过大**：只按输入 token 切（12000），不按题数——最大批次 87 题、单批 304s，p90 248s 逼近 300s 超时。
3. **连接错误就 fail fast**：一个批次 `IOException` 即设「判断服务不可用」并**取消该 stage 剩余全部批次**。

## 已修 / 未修

- 已修（`afd99bb` + `b963678`）：补问（深度 4）、chat 题数上限 40、HTTP/1.1 固定 + 4 次重试（1/2/4s 退避）。
- **未修**：单批连接错误仍会取消整个 stage。

## 一个被推翻的归因

所谓「242/469 丢失」的根因不是缺 ID，是**连接重置**：日志显示 10 个线程在同一秒 `Connection reset`；**改之前也是同样模式**（27 次重置，两次 10 个同一秒）→ 链路问题，不是代码问题。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[lab-bench]] | 承载该 judge 的评测台 |
| [[llm-gateway]] | 模型调用入口 |
| [[评测口径一致性]] | 判分不可靠 / 仲裁率问题的上游 |
| [[浏览器存储配额]] | 评测台另一个瓶颈（存储与渲染） |

# Citations

- 04 排障信号手册 §5.6
