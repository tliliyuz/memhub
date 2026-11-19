---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/llm-gateway-applesay
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/llm-gateway-applesay.md
  type: wiki
supersedes: []
tags:
- LLM
- 网关
- 打标
- 判分
tier: canonical
title: llm-gateway-applesay
updated_at: '2026-11-18T07:26:22Z'
---

> 打标/判分统一 LLM 网关 https://applesay-api-hup.applesay.cn/v1，必须直连；承载 qwen3.8-flash 等模型，模型可用性会漂移。

# llm-gateway-applesay

## Definition

sdp-tag 的打标与判分统一入口（LLM 网关）。

## Key Attributes

| 项 | 值 |
| --- | --- |
| base-url | `https://applesay-api-hup.applesay.cn/v1` |
| 网络策略 | ⚠️ **必须直连**，走代理会 timeout |
| 打标模型 | `qwen3.8-flash`（`llm.chat.model-name`） |
| 判分 provider | `llm.chat` / `llm.judge` 两套独立配置 |
| 探活接口 | `GET /v1/models`（`-H "Authorization: Bearer $KEY"`） |

### 7 把 LLM key（仅前缀）

| key 前缀 | 位置 | 用途 |
| --- | --- | --- |
| `sk-w7D1fBa7…` | 会话明文 | qwen 判分 1 |
| `sk-XIns9C45…` | 会话明文 | qwen 判分 2 |
| `sk-932zoWfR…` | 会话明文 | gpt 判分 1 |
| `sk-eu5TfPaz…` | 会话明文 | gpt 判分 2 |
| `sk-m6HP7wGe…` | 会话明文 | grok 仲裁 |
| `sk-VLQWYFtV…` | yml 默认值 + Judge 默认 | 打标 + 视觉默认 |
| `sk-Fb8GWrIc…` | 用户会话整把贴出 | 四臂实验 |

### 模型名

`qwen3.8-flash`、`gpt-6.1-sol`、`grok-4.7`、`deepseek-v4.1-flash-1017`（评测默认）。

## Relationships

- **代理策略**：直连 → [[proxy-routing-policy]]（与 [[system-one-typesafe]] 相反）
- **判分终点**：`llm.judge.provider` 可选 `llm`（ChatJudge）/ `typesafe`（[[system-one-typesafe]]）/ `ark`（[[ark-volces]]）
- **评测工具共用**：[[lab-accuracy-tool]] 的默认 base-url 与 Judge key 同源 → [[lab-evaluation-framework]]
- **凭据风险**：7 把 key → [[credential-leak-and-rotation]]

## 已知问题

- **模型可用性会漂移**：`qwen3.8-flash` 出现过 503、`qwen3.7-max` 读不了图、只有 `qwen3.6-plus` 能读图 → **跑批前先探一次**
- `sk-VLQWYFtV…` 被写进 `application.yml` 的 `api-key` 默认值
- `[Z]` 2026-10-22 用户给过一把专用 `LAB_ACCURACY_API_KEY` 并明确要求「用那个，不要用 yml 默认」——说明 key 轮换是**既有动作**

## Citations

- §5 LLM 网关与 key
- §5.2 `llm.judge.*` 与 `llm.chat.*` 是两套独立配置
- §5.3 模型可用性会变
