---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/proxy
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/proxy-转发故障分段定位.md
  type: wiki
supersedes: []
tags:
- 排障
- '502'
- 故障定位
tier: canonical
title: Proxy 转发故障分段定位
updated_at: '2026-11-18T07:26:22Z'
---

> Proxy 502 的分段排障范式：既有间歇性 502 收敛到 Proxy→上游段（10.4s/fetch failed/401 探测），也有配置挂载段故障（回退 DEFAULT_CONFIG + 占位上游）；两条根因并列、不可合并为单一结论。

# 定义

针对 [[DSH Desktop]] 间歇性 `DeepSeek Messages request failed (502)` 的分段定位方法：先用证据把链路切成“客户端 → Proxy”与“Proxy → 上游”两段，再把故障段收敛。

这是一种把 502 类故障**按链路分段收敛**的排障范式：用 Proxy 日志的时延与 `fetch failed`、容器健康状态、以及对上游的无凭据探测（401）等手段，判断故障发生在哪一段。

# 现象

- DSH 报 `DeepSeek Messages request failed (502)`，**重试有时恢复**（间歇性）。
- [[Memory Proxy]] 日志：失败发生在转发到上游 `/v1/messages` 时，多次约 **10.4 秒**后记录 `fetch failed`，随后 Proxy 返回 502。
- 另一类外观相似但性质不同：`start-proxy.sh` 显示 `[ok] tdai-proxy healthy`，但**所有请求 502**，见“分支二”。

# 两条并列的 502 根因分支

⚠️ 这两个根因**不可合并为一条结论**，必须并列检查。旧记录中的“故障段已收敛到 Proxy → 上游”仅适用于当时的间歇性 502 场景，不应外推为所有 502 的唯一结论。

## 分支一：Proxy → 上游段（既有结论）

既有现象：DSH 间歇性 502，重试有时恢复；[[Memory Proxy]] 日志在转发到上游 `/v1/messages` 时约 **10.4 秒**后记录 `fetch failed`，随后返回 502。

定位证据：

| 证据 | 结论 |
| --- | --- |
| Proxy 日志时延 ≈10.4s + `fetch failed` | 失败点在**转发到上游**阶段，而非客户端解析 |
| 三个容器健康 | 排除容器崩溃/未启动 |
| 日志无 HTTP 429 | 排除上游限流（至少当时未见） |
| 容器内 4 次无凭据探测均快速返回预期 401 | 上游**在探测当时**可达；不证明故障时刻可达 |

- 排查信号：Proxy 日志出现 `fetch failed` / 时延异常；对上游做无凭据探测返回 401（说明探测当时网络可达、只是缺凭据）；容器健康。
- 判据：容器可达但对上游的任何请求都失败，且已排除配置挂载问题 → 收敛到 Proxy→上游段。
- 局限：现有日志**无法细分** DNS 解析、TCP/TLS 握手、网关错误这三类失败。
- **未结论**：现有日志没有连接异常的底层原因，**无法细分** DNS 解析、TCP/TLS 握手、或网关断连。
- 后续需补：更细粒度的连接错误日志、故障时刻的主动探测、上游侧日志对齐。

## 分支二：配置挂载段（2026-11-10 新增）

- 现象：`start-proxy.sh` 显示 `[ok] tdai-proxy healthy`，但**所有请求 502**。
- 根因：Git Bash MSYS 路径转换把 `-v D:\...:/data/config.yaml` 的 `D:` 当成路径分隔符，挂载源被拼坏 → 容器内 `/data/config.yaml` 不存在 → 启动日志 `config not found — falling back to DEFAULT_CONFIG` → 实际上游退化为占位地址 `https://llm-upstream.example.com/v2/chat/completions`。
- 判据：`docker exec tdai-proxy head -5 /data/config.yaml` 读不到内容；`docker inspect` 的 `Mounts.Source` 含 `;C:\Program Files\Git`。
- 处置见 [[start-proxy 启动脚本]]。

> 容易误判之处：分支二在外观上「上游地址看起来是配置的地址」（如果只看 `.env`），实际容器内跑的是占位配置。**不要因为 `.env` 写对了就排除这一分支。**

# 第三类可区分症状

| 返回 | 含义 |
|---|---|
| 502 | 挂载段或上游段故障（见上两分支） |
| 503 `No available channel` | 上游仍是 memhub 而非 magpie，改配置没生效 |
| 401 `invalid user_key` | 反向串联（Magpie 在内层），见 [[凭据分层模型]] |

# 排障范式（可复用）

1. 读代理日志，看失败发生在**哪一次转发**、耗时多少。
2. 用容器健康状态排除本机服务问题。
3. 用**无凭据探测**验证上游可达性而不泄露凭据（见 [[凭据分层模型]]）。
4. 明确区分“探测时可达”与“故障时刻可达”，避免过度结论。
5. 若健康检查通过但**所有请求 502**，先检查配置挂载与启动日志是否回退到 `DEFAULT_CONFIG`（见分支二）。

# 相关实体与页面

[[Memory Proxy]]、[[DSH Desktop]]、[[applesay 上游模型服务]]、[[TencentDB Agent Memory]]、[[Magpie]]

- [[静默失效与健康检查盲区]]（互为排障分支；分支二的本质是健康检查盲区）
- [[级联代理拓扑与分层顺序]]（五步验证顺序即分段收敛的流程化表达）
- [[start-proxy 启动脚本]]
- [[凭据分层模型]]

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §4.1、§5.3
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`（旧 502 排障记录）
