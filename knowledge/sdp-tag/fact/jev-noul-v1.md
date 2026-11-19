---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/jev-noul-v1
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/四段结构-jev-noul-v1.md
  type: wiki
supersedes: []
tags:
- 协议
- 提示词
- 契约
tier: canonical
title: 四段结构 jev_noul_v1
updated_at: '2026-11-18T07:26:22Z'
---

> 成为唯一请求/响应协议的四段结构，删除全部 legacy 与 requestFormat 开关，老版本仅供审计。

# 定义

`jev_noul_v1` 是打标请求/响应的**唯一**格式协议（四段结构）。2026-10-21（`502b975`）删除「请求格式」选择器，移除全部 legacy / structured_v1 / structured_v2 分支。

# 意义

- 消除格式分叉：格式开关一旦存在，任何「跑一下旧提示词」的诉求都会与协议演进冲突。
- 统一校验入口：`LabQuestions.validateTemplate` 要求 `jev_noul_v1`，从代码层面阻止旧格式回潮。

# 删除范围

`LabRequestFormat` 枚举、`LabQuestionContent`、BO/VO/前端类型、IndexedDB 批次头里的 `requestFormat`、legacy 字符串拼接分支。

# 保留范围

提示词管理仍保留通用 System/User 能力（图片识别 `tag.image.recognition` 仍在用）；只有 `tag.lab.*` 固定为四段结构。

# 代价

- 老 chat_v1 版本留在 `sys_prompt_version` **仅供审计，不能再跑**。
- 任何后续「加个格式开关」的请求都与该决定冲突。
- 发布脚本 `script/sql/update/publish_sys_prompt_noul.sql`（幂等，按 code 发布最高版本）**必须按环境各跑一次**。

# 关联

- 相关实体：[[提示词管理]]、[[打标系统]]、[[Lab 实验台]]
- 相关概念：[[提示词短协议原则]]、[[短题号别名]]（同属 `tag.lab.*` 固定协议）

# Citations

- `02-方案选型与权衡.md` §2
