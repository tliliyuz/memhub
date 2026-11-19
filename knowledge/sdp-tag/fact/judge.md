---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/judge
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/judge-三值判定.md
  type: wiki
supersedes: []
tags:
- judge
- 三值判定
- unknown
- contradict
tier: canonical
title: judge 三值判定
updated_at: '2026-11-18T07:26:22Z'
---

> 评测侧 judge 输出 support / contradict / unknown；「矛盾」指标签不属于该商品，unknown 是弃权票。

# judge 三值判定

## 定义（实义）

评测侧 judge 对「商品—标签」对输出三值：`support` / `contradict` / `unknown`。

- 「矛盾」= `contradict`，含义是**标签不属于该商品**，**不是逻辑自相矛盾**。
- 「判不出」= `unknown`，是弃权票。
- **`unk` 这个缩写在代码和报表里不存在**，一律写 `unknown`。

## 打标侧 judge vs 评测侧 judge（同名两物）

| | **打标侧 judge** | **评测侧 judge** |
| --- | --- | --- |
| 是什么 | `llm.judge.provider` 决定判分源 | `tools/lab-accuracy official` 的三评（[[评测工具]]） |
| 输出 | 给候选打 0~1 的 `noul` | 判 `support / contradict / unknown` |
| 模型 | `qwen3.8-flash` / `jev-1.13.0` / `doubao`(ark) | `qwen3.8-flash` + `gpt-6.1-sol` + `grok-4.7` |

**说「judge 准不准」时，先问是哪一个**，见 [[判分模型清单]]。

## 与准确率口径的关系

- strict：`support / 全部输出标签`，**unknown 计入分母**。
- 另有「剔除 unknown」口径。
- 正式口径 `inference` 是「**允许 judge 合理推断**」，**不是**剔除 unknown，见 [[准确率口径]]。

## unknown 高不一定是模型错 `[D]`

可能是判定标准本身不存在。例如「静奢风要不要容忍小马刺绣」在「维度定义：无」的条件下无解——那 48 条 unknown 是**判定模糊**，见 [[维度]] 与 [[证据]]。

## unknown 在三评里是弃权票 `[D]`

三票各异或有效票不足 2 张时，维度门退 `unclear`、标签退 `unknown`，**都不进分母**，见 [[三评架构]]、[[门控]]。

## 一个反直觉的发现 `[Z]`

472 个「J1 判 support、J2/J3 都 unknown」的案例里，**454 个（96.2%）在 inference 口径下变成 support** → 那批分歧是 rubric 边界，不是数据缺失。

## 相关页面

[[准确率口径]] · [[证据]] · [[三评架构]] · [[判分模型清单]]

## Citations

- `01-术语实义.md` §7、§10 `[D][Z]`。
