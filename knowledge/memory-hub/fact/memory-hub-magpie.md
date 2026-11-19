---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/memory-hub-magpie
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/sources/memory-hub-magpie-级联配置手册.md
  type: wiki
supersedes: []
tags:
- 级联
- 配置手册
- 落地记录
- magpie
- memory-proxy
tier: canonical
title: Memory Hub × Magpie 级联配置手册
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-11-10 将 Memory Proxy(8096) 的上游改为 Magpie(3425) 的级联落地记录，含完整改法、五个关键坑位、五步验证清单、运维命令与回滚方式。

# 文档概要

本文档是一份**落地记录 + 复现手册**（配置手册性质，其中拓扑与端口部分可按架构文档归档），记录 2026-11-10 把 [[Memory Proxy]]（8096）的上游从 [[applesay 上游模型服务]] 切换为 [[Magpie]]（3425）的完整实践。

解决的原始困境：DSH 中配了两套 provider，**选 Magpie 的模型就没有记忆，选 [[Memory Hub]] 就没有模型自由，两者不可兼得**。

| provider | baseURL | 问题 |
|---|---|---|
| Memory Hub | `http://127.0.0.1:8096/dsh/default/v1` | 只有 deepseek 系列模型（是 Magpie 的子集） |
| Magpie | `http://127.0.0.1:3425/v1` | 模型丰富，但直连 3425 绕开 8096，记忆不会被记录 |

解决思路：把 Memory Proxy 的上游指向 Magpie，形成级联，详见 [[级联代理拓扑与分层顺序]]。

# 主要论断

1. **Memory Proxy 必须位于最外层** —— 它需要看到客户端原始请求才能注入 L2/L3 记忆并把对话归档成 L0；放在内层则记忆归属失真。
2. **Magpie 是「密钥替换」型网关** —— 反向串联（`DSH → Magpie → Memory Proxy`）必然 401 `invalid user_key`，这是「Proxy 在外层」的第二条独立理由。见 [[凭据分层模型]]。
3. **配置生效的唯一通道是 [[start-proxy 启动脚本]]** —— Proxy 只认 `--config /data/config.yaml`，不认环境变量，改完 `.env` 必须重跑脚本。
4. **两类故障都是静默的** —— 挂载失效仍 `healthy` 但全 502；开关关闭时模型正常回复但不记记忆。见 [[静默失效与健康检查盲区]]。

# 关键坑位（按踩坑代价排序）

| # | 坑位 | 现象 | 处置 |
|---|---|---|---|
| 4.1 | Git Bash MSYS 路径转换让 Docker 挂载静默失效 | 脚本显示 `[ok] tdai-proxy healthy`，但所有请求 502；日志 `config not found — falling back to DEFAULT_CONFIG`；实际上游变成占位地址 `https://llm-upstream.example.com/v2/chat/completions` | 启动加 `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'` |
| 4.2 | Proxy 只认 YAML 不认环境变量 | 改 `.env` 后不生效 | 重跑 [[start-proxy 启动脚本]] 生成 `.proxy-config/config.yaml` |
| 4.3 | `PROXY_ENABLE_*` 未显式设置 | 服务正常、模型正常回复，只是不记记忆 | 显式写 `PROXY_FULL_STACK/AUTH/TDAI/SESSION_INIT=1`，见 [[能力开关显式固化]] |
| 4.4 | DSH 有两套 provider 体系 | 改完 `llm-pi-ai` 的 providers，界面纹丝不动 | 改 `llm-deepseek`，见 [[DSH 双 Provider 体系与设置覆盖层]] |
| 4.5 | `settings.yaml` 覆盖 / 重写 `cordis.patch.yml` | 重启后配置丢失 | 优先改不在 `settings.yaml` 里的 `llm-deepseek` 段 |
| 4.6 | Magpie 不透传客户端密钥 | 反向串联 401 `invalid user_key` | 保持 Proxy 在外层 |
| 4.7 | Magpie 的 `/v1/messages` 不校验入站密钥 | 不带 `authorization` 仍 200 | 额度防护依赖 Magpie 自身配置，需确认其 LAN key 策略 |
| 4.8 | 模型名模糊匹配 | `/v1/models` 不含 `deepseek-v4.1-flash-1017` 但请求 200，`-1017-extra` 返回 404 | 用规范 id，见 模型 ID 解析与路由组 |

# 配置改动清单

- `TencentDB-Agent-Memory-local/.env`：`PROXY_UPSTREAM_URL=http://host.docker.internal:3425/v1`、`PROXY_UPSTREAM_API_KEY=<magpie 网关密钥>`、`PROXY_UPSTREAM_MODEL=auto/deepseek-v4.1-flash`，外加四项 `PROXY_ENABLE_*`。
- `~/.dsh/profiles/desktop/cordis.patch.yml`：`llm-deepseek.config.baseURL = http://127.0.0.1:8096/dsh/default`，`config.models` 追加 Magpie 模型（用 `inputModalities`，不是 `input`）。
- 可选：`agent-default-model` 设为 `provider: deepseek-official`、`model: auto/deepseek-v4.1-flash`、`reasoningEffort: high`。
- 密钥只从 Magpie 界面 / `~/.config/magpie/providers.json` 读取，**不写入 wiki**。

# 验证清单（五步，须按序通过）

1. **上游是否正确** —— `docker exec tdai-proxy head -12 /data/config.yaml`，期望 `upstream.url = http://host.docker.internal:3425/v1`。
2. **容器到 Magpie 是否通** —— `docker exec tdai-proxy curl … http://host.docker.internal:3425/`，期望 200。
3. **模型能否穿透（核心）** —— 向 `8096/dsh/default/v1/chat/completions` 发 `gpt/gpt-6.1-sol`，期望 200；502 看上游客（§4.1），503 `No available channel` 说明上游仍是 memhub 而非 magpie。
4. **注入管线是否在跑** —— `docker logs tdai-proxy --tail 100` 查 `injection.pipeline.done`，期望 `errorCount=0`，injectors 含 skill/knowledge/tdai-memory。
5. **记忆是否真在涨** —— 面板 `POST /api/v1/chat-memory/layer` 查 L0/L1 的 `total` 应增长。

# 运维命令

面板 API 前缀是 `/api/v1/`（不是 `/api/`），`limit` 硬上限 100。常用三组：`chat-memory/layer`（按 L0–L3 数计数）、`agent-overview/bootstrap`（团队资产总览）、`knowledge/wiki/list`（Wiki 列表）。请求头需 `x-tdai-service-id` 与 `x-tdai-user-key`（`sk-mem-` 用户密钥）。

# 结果基线（2026-11-10 落地后）

| 项 | 值 |
|---|---|
| 8096 上游 | `http://host.docker.internal:3425/v1`（Magpie） |
| DSH `llm-deepseek` 模型数 | 2 → **66** |
| 三容器状态 | 全部 healthy |
| 注入管线 | `hookCount=6, totalBlockCount=5, errorCount=0` |
| `auto/deepseek-v4.1-flash` | 200，记忆正常累积 |
| `gpt/gpt-6.1-sol` / `workbuddy/*` / `trae-cn/*` | 均 200 |

# 回滚与备份

各步骤均有 `*.bak.20261110` 备份：`.env`、`.proxy-config/config.yaml`、`cordis.patch.yml`（原始与首次改动前两份）。回滚后重跑 [[start-proxy 启动脚本]]（带 MSYS 变量）并重启 DSH。

# 与既有记录的冲突点

- 旧记录 [[TencentDB Agent Memory 本地部署与 SDP Tag 使用记录]] 记载 8096 上游为 applesay 直连；**本文档自 2026-11-10 起改为经 [[Magpie]] 级联**。两者为时间点先后关系，保留历史而非覆盖。
- 旧记录的 502 排障结论落在「Proxy → 上游」段；本文档的 502 根因是**配置挂载段**（回退 DEFAULT_CONFIG + 占位上游）。二者是并列分支，见 [[Proxy 转发故障分段定位]]。

# Citations

- 源文件：`memhub-magpie-级联配置手册.md`

- §4.8 补充实测数据：Magpie 的 `/v1/models` 在 2026-11-10 共返回 **64 个 id**，命名形态有三类 —— `provider/model`、`auto/model`、`group/never-stuck`；因此解析是按前缀 / 模糊匹配而非精确查表（详见 [[模型 ID 解析与路由组]]）。
- 回滚不仅恢复原上游并重启，还需走一遍与新配置首次上线**同等的验证**才算完成，见 [[start-proxy 启动脚本]]。
