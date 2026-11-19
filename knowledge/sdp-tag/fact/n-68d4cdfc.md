---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-68d4cdfc
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/证据.md
  type: wiki
supersedes: []
tags:
- evidence
- judge
- reasoning_content
- 溯源
tier: canonical
title: 证据
updated_at: '2026-11-18T07:26:22Z'
---

> 「evidence」指三件不同的事——Judge 判定依据、tag_task_evidence 落库证据、track.reason 固定枚举；模型原文在 reasoning_content。

# 证据

## 定义（实义）——三个不同的东西

| 名字 | 是什么 |
| --- | --- |
| `pairs-evidence.xlsx` 的 `evidence` 列 | **Judge 的判定依据**（「为什么判 support/contradict/unknown」） |
| `tag_task_evidence` 表 | 打标过程的证据落库（gzip LONGBLOB） |
| 回写的 `track.reason` | **固定枚举**，不是模型原文 |

## 曾被纠正过一次 `[D]`

> 用户原话：「你这个 evidence 是不是搞错了，这个表里的是 judge 的判定依据，而不是判断模型的判断依据」。

搞错会把「模型的假设」当成「数据能证明的结论」，见 [[judge 三值判定]]。

## 连带的重量级结论 `[D]`

Judge 的 prompt 里也拼维度定义。那一轮定义全空（见 [[维度]]），所以 **90.0% 是模型与 Judge 双盲的基线**——「补定义 → 准确率上升」可能只是两边在新口径下达成一致。

## 模型原始理由在哪

`reasoning_content`，取证路径：

```
run.stages[label].batches[].response.choices[0].message.reasoning_content
```

## `track.reason` 的枚举

图文互证 / 文字推断 / 图片推断 / 明确不符 / 证据不足（提交 `b506436` 改的，与对方文档「模型判断依据原文」口径不一致）。

## 溯源物

- `pairs-evidence.xlsx`（评测产物）。
- `evidence/` 下三份提炼稿：`[C]` Codex / `[D]` DSH / `[Z]` zcode 的逐条原文引用，见 [[01 术语实义]]。

## 相关页面

[[准确率口径]] · [[三评架构]] · [[对方 search 服务]]

## Citations

- `01-术语实义.md` §5、出处索引 `[D][Z]`。
