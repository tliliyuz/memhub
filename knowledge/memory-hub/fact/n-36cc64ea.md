---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/n-36cc64ea
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/模型-id-解析与路由组.md
  type: wiki
supersedes: []
tags:
- 模型路由
- 配置
tier: canonical
title: 模型 ID 解析与路由组
updated_at: '2026-11-18T07:26:22Z'
---

> Magpie 对模型名做前缀模糊匹配（-1017 请求 200、-1017-extra 404），建议统一使用 auto/deepseek-v4.1-flash 这类带兜底的路由组或 provider/model 这类落点确定的写法。

# 定义

在 [[级联代理拓扑与分层顺序]] 的模型层上，[[Magpie]] 收到请求时并非严格按 `body.model` 精确查表，而是做**前缀 / 模糊匹配**：只要模型名能匹配到已注册的模型族前缀，就路由到该族；匹配不上则直接报错。

因此同一个模型可以有多种写法，但**落到哪个真实 provider 并不完全由你写的字符串决定**。这是"能通 ≠ 该这么写"的根因，也是选择模型 id 时必须区分"稳定性优先"与"归因精确优先"的原因。

# Schema

| 维度 | 行为 |
| --- | --- |
| 匹配方式 | 前缀 / 模糊匹配，非精确查表 |
| 命中 | 落入匹配到的模型族（如 `deepseek-v4.1-flash` 族） |
| 未命中 | 404，错误文案 `magpie knows no model ...` |
| 请求链路 | 客户端 → [[Memory Proxy]]（原样透传 `body.model`）→ [[Magpie]] → 上游 provider |

# Examples：关键行为（2026-11-10 实测）

实测对象：`POST http://127.0.0.1:3425/v1/messages`

| 请求的 model | 结果 | 说明 |
| --- | --- | --- |
| `deepseek-v4.1-flash` | 200 | 精确命中 |
| `deepseek-v4.1-flash-1017` | 200 | **`/v1/models` 里并无此 id**，靠前缀匹配落到 `deepseek-v4.1-flash` 族 |
| `deepseek-v4.1-flash-1017-extra` | 404 | 超出前缀边界，报 `magpie knows no model ...` |
| `totally-fake-model-xyz` | 404 | 未命中任何族 |

结论：`-1017` 后缀能通，但**不是显式登记的名字**，属于模糊匹配的副作用；再加一段后缀即越界失败。`deepseek-v4.1-flash` 族的真实落点之一是 [[applesay 上游模型服务]]。

# 模型命名形态

Magpie 的 `/v1/models`（2026-11-10 共 64 个 id）有三种命名形态：

| 形态 | 示例 | 含义 |
| --- | --- | --- |
| `provider/model` | `trae-cn/deepseek-v4.1-flash`、`workbuddy/kimi-k3.1-pro` | 指定具体 provider，落点确定，**无兜底** |
| `auto/model` | `auto/deepseek-v4.1-flash`、`auto/glm-5.3` | **路由组**，在多家间自动选可用通道，带兜底，落点不定 |
| `group/never-stuck` | `group/never-stuck` | 稳定性优先的路由组 |

# 选择建议

| 诉求 | 选法 | 代价 |
| --- | --- | --- |
| 优先稳定、永不卡住 | `auto/*` 或 `group/never-stuck` | 落点不确定 |
| 记忆里要精确的模型归因 | `provider/model`（如 `trae-cn/deepseek-v4.1-flash`） | 落点确定但无兜底 |
| 历史遗留写法 | 不再写 `deepseek-v4.1-flash-1017`，改为 `auto/deepseek-v4.1-flash` | — |

# 与记忆归因的关系

[[Chat Memory]] 记录的 `modelId` 是**请求发出时的名字**，而不是最终落地的真实模型。若用 `auto/*` 或 `group/never-stuck` 路由组，记录到的是组名，模型归因会失真；若需要精确归属，必须使用 `provider/model` 形式。该口径已并入 [[Chat Memory]] 页。

# 口径说明

`/v1/models` 的 id 数量存在两个时点/口径的计数：本文实测为 **64 个**，而 [[DSH Desktop]] 侧记录"追加 Magpie 模型后可选模型由 2 个增至 66 个"。二者相差 2，属于计数时点或统计口径不同，不构成互斥结论，引用时应注明出处与时间。

# 相关实体

[[Magpie]]、[[Memory Proxy]]、[[applesay 上游模型服务]]、[[级联代理拓扑与分层顺序]]、[[Chat Memory]]、[[DSH Desktop]]

# Citations

- `memhub-magpie-级联配置手册.md`（§4.8 模型名模糊匹配），本文为该节的派生概念页
