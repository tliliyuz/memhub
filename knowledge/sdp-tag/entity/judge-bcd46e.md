---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/judge-bcd46e
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/judge-判定模型.md
  type: wiki
supersedes: []
tags:
- 打标系统
- 评测
- 判定
tier: canonical
title: Judge 判定模型
updated_at: '2026-11-18T07:26:22Z'
---

> 对打标结果做二次判定并产出 evidence 的判定模型，与打标模型构成两套口径。

# 定义

kind: service

Judge 判定模型对 [[打标引擎（TagEngine）]] 产出的候选标签做二次判定，输出 `pairs-evidence.evidence`——**这是 Judge 的判定依据，不是打标模型的理由**。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 输出字段 | `pairs-evidence.evidence`（Judge 视角）；模型原话在 `reasoning_content` |
| 判定依据来源 | [[维度图谱（graph）]] 的取值——图谱取值错，定义写什么都救不了（A5） |
| `resolveJudge` | 未配置 Judge / 返回 null 时，空结果产生在 Judge **之前**（C7） |
| 统计口径 | `support/(support+contradict)` 只是剔除弃权，**不能代替准确率**（F4） |
| 评测协议 | 三评协议（F3），基线与实验须过同一协议 |

# 关系

- ↔ [[打标引擎（TagEngine）]]：双口径。定义类改动必须同时看「模型是否照做」与「Judge 是否照判」；两者不一致时是负收益（A1）。
- ↔ [[维度图谱（graph）]]：判定依据直接取自图谱取值与补全关系。
- ↔ [[分维阈值与准确率口径]]：Judge 判死与否决定「已产出标签对」这张分母的构成。
- ↔ [[打标评测方法论]]：三评协议、干净 A/B、噪声基线都在 Judge 层面执行。

# 常见归因错误

- **把 evidence 当模型依据**（A4）：由此得出的「模型缺判据 / 模型被骗了」只是**推断**，结论被降级为假设；正解是读 `reasoning_content`。
- 把 Judge 判死当作模型错误：A1 中 68 条「父类标签」在图谱里本就是合法取值，Judge 按新排他规则判死，是**规则与数据打架**。

# Citations

- A1、A4、A5、C7、F3、F4；出处见 [[03-失败与被推翻]]。
