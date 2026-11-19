---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/n-47fdaf74
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/提示词管理.md
  type: wiki
supersedes: []
tags:
- 提示词
- 版本管理
tier: canonical
title: 提示词管理
updated_at: '2026-11-18T07:26:22Z'
---

> 基于 sys_prompt_version 的提示词发布模块，按 code 发布最高版本，tag.lab.* 固定为四段结构。

# 定义

提示词管理模块（表 `sys_prompt_version`）负责提示词的版本化存储与发布，按 code 发布**最高版本**。

# 关键属性

- **保留通用能力**：仍支持通用 System / User 提示词（图片识别 `tag.image.recognition` 还在用）。
- **`tag.lab.*` 固定四段结构**：由 `LabQuestions.validateTemplate` 强校验，见 [[四段结构 jev_noul_v1]]。
- **老版本仅供审计，不能再跑**（chat_v1 等 legacy 版本保留在表中但不可执行）。
- **发布脚本**：`script/sql/update/publish_sys_prompt_noul.sql`（幂等），**必须按环境各跑一次**。
- **版本线索**：最终定版为 `scene v3 + dim v3 + label v7`（lab 显式 ID），published 指针仍指向 v1/v1/v1。各版本演进表见 [[提示词短协议原则]]。

# 关系

- 为 [[打标系统]] 与 [[Lab 实验台]] 提供提示词。
- 与 [[标签图谱]] 分工：**语义放标签备注/维度定义，提示词只放通用判断协议**。
- 四段结构与 [[短题号别名]] 同属 `tag.lab.*` 固定协议。

# Citations

- `02-方案选型与权衡.md` §1、§2
