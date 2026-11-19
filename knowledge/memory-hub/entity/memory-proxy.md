---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: memory-hub/entity/memory-proxy
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/memory-proxy.md
  type: wiki
supersedes: []
tags:
- 服务
- 代理
- proxy
- 记忆注入
- 级联
- 级联拓扑
- '8096'
- bridge
tier: canonical
title: Memory Proxy
updated_at: '2026-11-18T07:26:22Z'
---

> 监听 8096 的模型与能力代理（容器 `tdai-proxy`），2026-11-10 起上游由 applesay 改为 Magpie，是级联拓扑最外层、记忆注入与 L0 落库的发生点；向客户端提供可用 Skill 列表与 L3/L2 记忆索引；其 bridge 端点因会话耦合不被 MCP 使用。

# Memory Proxy

## 定义

`memory-proxy`（容器 `tdai-proxy`）是 [[TencentDB Agent Memory]] 的模型/能力代理，也是面向客户端的统一入口：对客户端提供统一入口，对上游转发模型请求，同时暴露记忆与能力清单（可用 [[Skill]] 列表、[[记忆分层 L0–L3]] 中的 L3 长期画像与 L2 场景索引，亦即为 [[Chat Memory]] 提供 L3/L2 索引）。它向上游 `/v1/messages`、`/v1/chat/completions` 转发模型请求。

自 **2026-11-10** 起，其上游由 [[applesay 上游模型服务]] 改为 [[Magpie]]（`http://host.docker.internal:3425/v1`），成为 [[级联代理拓扑与分层顺序]] 的**最外层**。实际链路为：客户端 → Proxy（完成记忆注入与 L0 落库）→ [[Magpie]]（3425，模型路由/额度）→ 各家上游模型服务。配置由 [[start-proxy 启动脚本]] 从 `.env` 生成 `config.yaml` 挂载生效。

## 关键属性

| 属性 | 值 |
| --- | --- |
| 容器 | `tdai-proxy` |
| 端口 | 8096 |
| 端口绑定 | **记录冲突**：旧记录为「仅 127.0.0.1」；新记录为「0.0.0.0」。绑定与 LAN 可见性详见 [[本地部署拓扑与回环绑定]] |
| DSH 入口 | **记录冲突**：旧记录为 `http://127.0.0.1:8096/dsh/default`（不加 `/v1`）；新记录为 `http://127.0.0.1:8096/dsh/default/v1` |
| 上游（2026-11-10 起） | `http://host.docker.internal:3425/v1` → [[Magpie]] |
| 上游（此前 / 旧记录） | [[applesay 上游模型服务]] 的 `/v1/messages` 直连 |
| 暴露能力 | [[Skill]] 可用列表、L3 长期画像与 L2 场景索引 |
| 记忆职责 | L0 对话原文落库、L1 原子记忆召回、L2/L3 上下文注入 |
| 桥接端点 | `memory-bridge` / `skill-bridge` 等，供**活跃会话**内的 agent 读取记忆与 Skill；按 `x-conversation-id` 反推身份，不校验独立密钥；脱离活跃会话时返回 `40101 session not initialized` |
| 配置来源 | `.proxy-config/config.yaml`（由 [[start-proxy 启动脚本]] 从 `.env` 生成并挂载） |
| 启动参数 | `--config /data/config.yaml`（无环境变量覆盖通道） |

## 分层定位为何必须在最外层

1. **记忆归属**：只有看到**客户端原始请求**，才能正确注入上下文并把对话归档成 L0；若放在内层，Magpie 已改写过的请求会让记忆归属失真。
2. **凭据归属**：[[Magpie]] 是密钥替换型网关，反向串联必然 401 `invalid user_key`；只有 `sk-mem-` 用户密钥能进 8096。见 [[凭据分层模型]]。上游凭据由服务端持有，客户端只用 `user_key`。

## 关键边界：Proxy 不是所有读取路径的必经点（2026-11-10）

离线 MCP 场景实测（见 [[Team Brain MCP]] / [[MCP 双后端只读接入]]）：

- `memory-bridge`、`skill-bridge`（8096）在**脱离活跃会话**时一律返回 `40101 session not initialized`，因此 [[Team Brain MCP]] 弃用这两个端点。
- Chat Memory / Skill 改为直连面板／[[Memory Hub]] 8125（`/api/v1` + `sk-mem-` 用户密钥），Wiki / 代码图谱直连 [[Memory Knowledge]] 8424 的 `/v3` 只读端点（无需密钥）。
- 结论：**Proxy 是模型链路的必经点，但不是只读检索链路的必经点**；两条链路平行，检索不经过 8096。

### 为什么 MCP 不用它的 bridge（2026-11-10 结论）

`memory-bridge` / `skill-bridge` **在 MCP 场景不可用**：

- 脱离活跃 DSH 会话时一律返回 **`40101 session not initialized`**。
- bridge 的身份来源是 `x-conversation-id`——从会话 id 反推调用者，不校验独立密钥。
- MCP server 是任意 agent 拉起的独立 stdio 子进程，**没有会话上下文**。
- 因此 [[Team Brain MCP]] 的 [[Chat Memory]] / [[Skill]] 工具改走 [[Memory Hub]]（8125）的 `/api/v1` + `sk-mem-` 用户密钥。

这是「会话耦合鉴权无法服务无会话进程」的直接案例，见 [[MCP 双后端只读接入]]。

## 配置要点

- 上游 URL 必须用 `host.docker.internal:3425`，**不能用 `127.0.0.1:3425`**（容器内回环是容器自己）。
- base 末尾带 `/v1`：`joinUrl` 会在 base 后拼 `/messages` 或 `/chat/completions`，若 base 已含 `/v1` 则不再补。
- 能力开关必须显式开启（`PROXY_FULL_STACK/AUTH/TDAI/SESSION_INIT=1`），否则记忆静默失效，见 [[能力开关显式固化]]；缺 `PROXY_ENABLE_*` 亦会退化为全关闭。
- `.env` 改动后必须重跑 [[start-proxy 启动脚本]]。

## 关系

- 组成：[[TencentDB Agent Memory]] 的四个服务之一（见 [[本地部署拓扑与回环绑定]]）
- 上游/下游方向命名存在记录冲突：旧记录称 [[Magpie]] 为 Proxy 的**上游**（2026-11-10 起）/ [[applesay 上游模型服务]]（此前）；新记录沿请求转发方向称其为**下游**。实际链路均为 客户端 → Proxy → Magpie → 各家上游模型服务。转发时上游凭据由服务端持有 → [[凭据分层模型]]
- 下游消费者/客户端：[[DSH Desktop]]、Codex、Claude Code；DSH 等客户端的模型调用链为 `Agent → 8096 → 3425`，见 [[级联代理拓扑与分层顺序]]
  - 与 [[DSH Desktop]]：内置提供商经该入口接入，会话可绑定 [[Memory Agent]] 并自动归档
  - 与 [[Codex Desktop]]：官方供应商直连上游，**不经过** Proxy（因此无自动归档）
- **MCP 检索链不经过它**——检索链平行于模型链
- 同平台服务：[[Memory Hub]]、[[Memory Core]]、[[Memory Knowledge]]
- 依赖：[[Memory Core]]（记忆读写）、[[Memory Hub]] / [[Memory Knowledge]]（资产检索）
- 与 [[Chat Memory]]：提供 L3/L2 索引，Agent 按需下钻 L0/L1 → [[记忆分层 L0–L3]]
- 与 [[Skill]]：提供可用 Skill 列表
- 只读检索链路：[[Team Brain MCP]] / [[MCP 双后端只读接入]] 不使用 8096 的 bridge 端点，改直连 8125 与 [[Memory Knowledge]] 8424
- 配置通道：[[start-proxy 启动脚本]]

## 已知问题 / 排障线索

- [[Proxy 转发故障分段定位]]：DSH 间歇性 502，约 10.4 秒后 `fetch failed`，故障段已收敛到 Proxy → 上游；现有日志无法细分 DNS / TCP·TLS / 网关断连。
- **502 的两个独立根因分支**：
  1. 上游不可达（旧结论，见 [[Proxy 转发故障分段定位]]）；
  2. **配置未挂载成功** → 回退 `DEFAULT_CONFIG` → 上游是占位地址 `https://llm-upstream.example.com/v2/chat/completions`（MSYS 路径转换所致，见 [[start-proxy 启动脚本]]）。
- **503 `No available channel`**：说明上游仍是 memhub 而非 magpie，上游没改成功。
- 注入管线健康：`docker logs tdai-proxy --tail 100 | Select-String 'injection.pipeline.done'`，期望 `errorCount=0`，injectors 含 skill/knowledge/tdai-memory。
- 挂载自检：`docker exec tdai-proxy head -5 /data/config.yaml`。

## Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md`（记录中亦写作 `memory-hub-magpie-级联配置手册.md`）§1、§2、§3.2、§4.1–4.3、§5
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`（历史拓扑与 applesay 直连记录）
- `team-brain-mcp-接入指南.md` §1、§7
