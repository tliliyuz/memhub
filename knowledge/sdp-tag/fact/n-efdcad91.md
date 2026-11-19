---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-efdcad91
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/提示词与配置版本演进.md
  type: wiki
supersedes: []
tags:
- 提示词
- 版本管理
- 配置
tier: canonical
title: 提示词与配置版本演进
updated_at: '2026-11-18T07:26:22Z'
---

> scene / dim / label 提示词版本号与术语改动（场景→行业）必须绑定日期引用，否则无法判断是哪一个版本的行为。

# 定义

打标系统的三类提示词（scene / dim / label）各有独立版本号，且术语与结构会随时间改动。任何引用都必须绑定日期与版本号，否则不可复现。

# 版本演进记录

| 日期 | 变更 | 说明 |
| --- | --- | --- |
| 10-20 | A v1/v1/v1 → B v2/v2/v3 → C v3/v3/v4 | B 组 tokens +62.6%，**被否** |
| 10-20 | 定版 scene v3 + dim v3 + label v7 | 79 件商品验证 |
| 10-21 | scene v4 / dim v4 / label v8 | 配合 [[四段结构协议]] 成为唯一协议 |
| 10-25 | dim v6 / label v13 | **取消 Criteria** |
| 10-26 | 超限语义组自动拆分 | 根因是 label **v11** 太长 |
| 10-27 | 术语「场景」→「行业」 | **仅前端展示层**，提交 `288d0b3` |
| 10-27 | 根标签规则 | 别名不进候选 |
| 10-28 | 定义被**清空** | 141 个 `dimension_definition` → NULL |

# Significance

- 是 [[阶段演进]] 的伴生线：维度阶段取消后，dim 提示词的版本仍会被历史数据引用。
- 「场景 → 行业」只是展示层改动（`288d0b3`），**不要在文档中据此推断领域模型变更**——这是 [[仲裁口径]] 规则 1/2 的典型应用场景。
- 10-28 的 `dimension_definition` 清空使「按定义判分」的历史口径不可重现，必须在历史章节标注。

# Related Entities

- [[商品打标实验台]]
- [[正式打标链路]]

# Citations

- `00-时间线与仲裁口径.md` §1 时间线（10-20、10-21、10-25、10-26、10-27、10-28 条目）
