---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/n-bead1fba
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/打标侧.md
  type: wiki
supersedes: []
tags:
- 协作边界
- 角色
tier: canonical
title: 打标侧
updated_at: '2026-11-18T07:26:22Z'
---

> 即「我们 / 用户」，负责 lab、prompts、阈值与 judge 调用，不直接修改图谱表。

# 打标侧

## 定义

文档中的「用户 / 我们」，负责打标部分：[[打标实验台]]、prompts、[[阈值体系]]、judge 调用。

## 关键属性

- **不拥有** [[知识图谱]] 内容（场景/维度定义、标签备注、标签关系）。
- 拥有的可调项：阈值、prompt、模型选择、评测口径。
- 打标侧 judge 自身有两条实现路径，见 [[chat-judge 双路径]]。

## 关系

- 与 [[图谱团队]] 构成协作边界，见 [[图谱归属与协作边界]]。
- 通过 [[评测工具]] 产出 [[准确率口径]] 结论。

## 易误解

- 发现图谱内容问题时的正确动作是**报告证据 + 建议措辞**，不是直接改表。

## Citations

- `01-术语实义.md` §3「图谱归属边界」`[Z]`。
