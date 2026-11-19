---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/ark-volces
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/other/ark-volces.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: ark-volces
updated_at: '2026-11-18T07:26:22Z'
---

# ark-volces

## Definition

火山方舟（doubao）提供的 SystemOne 协议判分终点，作为 `llm.judge.provider=ark` 时的 LLM 后端。

## Key Attributes

| 项 | 值 |
| --- | --- |
| base-url | `https://ark.cn-beijing.volces.com/api/v1/systemone` |
| 必需请求头 | `ark-beta-systemone-api: true` |
| judge provider 键 | `ark` |

## 三个协议坑 `[Z]`

1. **必须带 `ark-beta-systemone-api: true` 头**，否则 404 且空 body
2. **图片 state 必须是数组** `[{type:text}, {type:image,image_url:data URI}]`。**嵌在对象里模型看不见**（红色图片只判 0.05）
3. Windows 下 `curl -d '中文'` 产生非法 UTF-8，**用 `-d @file`**

另一个坑：**`404 ModelNotOpen` 可能间歇出现**，即使模型已启用——重试即可。

## 分数分布

⚠️ **Ark 的分数会堆在 0.99+**：2,308 个命中里 1,582 个 ≥0.999。

→ **0.7 阈值对 Ark 太松，要用 0.999**，见 [[threshold-configuration]]。

## Relationships

- **平行终点**：[[system-one-typesafe]]、[[llm-gateway-applesay]]（ChatJudge）
- **阈值影响**：[[threshold-configuration]]
- **网络**：`*.volces.com` 走代理

## Citations

- §5 LLM 网关与 key（Ark 行）
- §5.1 Ark（doubao）的三个协议坑
