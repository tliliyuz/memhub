---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/chat-judge
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/chat-judge-双路径.md
  type: wiki
supersedes: []
tags:
- judge
- 双路径
- 稳定性
tier: canonical
title: chat-judge 双路径
updated_at: '2026-11-18T07:26:22Z'
---

> JudgeModel.Provider.LLM（本地，会补问，稳）与 ChatJudgeModel（远端，不补问，差）并存，是实验台端到端不如 A/B 稳的真因。

# chat-judge 双路径

## 定义（实义）`[Z]`

打标侧 judge 有两条实现路径并存：

| | `JudgeModel.Provider.LLM` | `ChatJudgeModel` |
| --- | --- | --- |
| 配置 | `llm.judge.provider: llm` | 自己的 `llm.chat` 块 |
| 缺答案补问 | **会**（题数减半重问） | **不会** |
| 来源 | 本地，2026-10-27 加 | 远端（hu.jingchao），2026-10-26 加 |
| 稳定性 | 好 | 差 |

## 意义

**这是「[[打标实验台]] 端到端不如 100 件 A/B 稳定」的真因——不是模型问题，是路径不同。**

## 易误解

- 把稳定性差异归因到模型能力或数据量，忽略了走的是哪条路径。
- 与评测侧 judge 混谈，见 [[judge 三值判定]]。

## 相关页面

[[判分模型清单]] · [[评测工具]] · [[打标服务]]

## Citations

- `01-术语实义.md` §13 `[Z]`。
