---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/magpie
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/magpie.md
  type: wiki
supersedes: []
tags:
- 模型网关
- 级联
- 上游
tier: canonical
title: Magpie
updated_at: '2026-11-18T07:26:22Z'
---

> 宿主机进程 magpie.exe，监听 3425（127.0.0.1 + LAN），只做模型路由/兜底/计价/额度的统一模型网关，本方案中作为 Memory Proxy 的上游。

# 定义

Magpie 是运行在**宿主机**上的统一模型网关（进程 `magpie.exe`），监听 `3425`（绑定 127.0.0.1 + LAN）。它**只做模型路由 / 兜底 / 计价 / 额度**，不承担任何记忆职责。

在 [[级联代理拓扑与分层顺序]] 中位于 [[Memory Proxy]] 之后、各家上游 provider 之前：

```
8096 Memory Proxy → 3425 Magpie → applesay / gpt / workbuddy / trae-cn / qoder-cn …
```

# 关键属性

| 属性 | 值 |
|---|---|
| 形态 | 宿主机进程 `magpie.exe`（非 Docker 容器） |
| 端口 | 3425 |
| 绑定 | 127.0.0.1 + LAN |
| 职责 | 模型路由、兜底、计价、额度 |
| 密钥来源 | Magpie 界面 / `~/.config/magpie/providers.json`（不写入 wiki） |
| 下游 provider | [[applesay 上游模型服务]]、gpt、workbuddy、trae-cn、qoder-cn 等 |

# 行为特征（踩坑要点）

- **密钥替换型网关**：收到客户端的占位 token（如字面量 `magpie`）会替换成自己 provider 配置里的真实密钥再发上游。因此若让 `DSH → Magpie → Memory Proxy`，Memory Proxy 只认 `sk-mem-` 用户密钥 → **401 `invalid user_key`**。详见 [[凭据分层模型]]。
- **`/v1/messages` 不校验入站密钥**：实测不带任何 `authorization` 头请求 `3425/v1/messages` 仍返回 200，额度防护依赖 Magpie 自身配置（需确认 LAN key 策略）。
- **模型名模糊匹配**：`/v1/models` 不含 `deepseek-v4.1-flash-1017` 但请求返回 200（前缀匹配落到 `-flash` 族），`-1017-extra` 返回 404。见 模型 ID 解析与路由组。
- 容器视角下 `127.0.0.1:3425 → 000`、`host.docker.internal:3425 → 200`，见 [[本地部署拓扑与回环绑定]]。

# 关系

- 上游被 [[Memory Proxy]] 调用（`PROXY_UPSTREAM_URL=http://host.docker.internal:3425/v1`）。
- 下游之一为 [[applesay 上游模型服务]]。
- 模型清单被 [[DSH Desktop]] 的 `llm-deepseek.config.models` 引用。
- 模型清单拉取：`Invoke-RestMethod -Uri 'http://127.0.0.1:3425/v1/models' -Headers @{'authorization'='Bearer <magpie 密钥>'}`。

# Citations

- `memhub-magpie-级联配置手册.md` §1、§2、§3.2、§4.6–4.8
