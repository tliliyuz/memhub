---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/lab-accuracy-tool
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/lab-accuracy-tool.md
  type: wiki
supersedes: []
tags:
- 评测工具
- Python
- lab-accuracy
tier: canonical
title: lab-accuracy-tool
updated_at: '2026-11-18T07:26:22Z'
---

> 离线评测工具 tools/lab-accuracy，三评 + 仲裁（qwen/gpt/grok），数据落 .local/lab-accuracy/（已忽略）。

# lab-accuracy-tool

## Definition

`tools/lab-accuracy` 目录下的离线评测工具，用于对打标结果做三评 + 仲裁打分。

## Key Attributes

| 项 | 值 |
| --- | --- |
| Judge key 环境变量 | `LAB_ACCURACY_API_KEY` / `LAB_ACCURACY_KEY_GPT` / `LAB_ACCURACY_KEY_GROK` |
| 默认 base-url | `https://applesay-api-hup.applesay.cn/v1`（`judge.py:24`） |
| 默认模型 | `deepseek-v4.1-flash-1017`（`judge.py:23`） |
| 三评默认 | `qwen3.8-flash` + `gpt-6.1-sol` + `grok-4.7` |
| 原始数据目录 | `.local/lab-accuracy/runs/`（**Git 忽略**） |

## Relationships

- **框架说明**：[[lab-evaluation-framework]]
- **共用网关**：[[llm-gateway-applesay]]
- **登录账号**：[[lab-admin-account]]
- **前置条件**：[[isolated-test-db-guard]]

## 已知问题

- ⚠️ **镜像 curl 下载会超时** → 从之前的 run 目录 `seed` 图片（文件名规则 `pid-urlhash.jpg`）
- ⚠️ **部分/中止的 score run 会污染续跑** → 重跑前删 `chunks.jsonl` 和 `scoring-state.json`
- ⚠️ **`--reuse-baseline` 按输入指纹匹配**，指纹变了会「禁止复用」
- ⚠️ **`--rubric` 会进提示词哈希，续跑必须一致**，否则会拒绝续跑
- **从 `application.yml` 取 key 的正确 sed**：`sed -E 's/.*\$\{[A-Z_]+:([^}]*)\}.*/\1/'`；模式写错会发出**假 key**，然后 401 会误导你以为权限问题

## Citations

- §7 评测工具 tools/lab-accuracy
