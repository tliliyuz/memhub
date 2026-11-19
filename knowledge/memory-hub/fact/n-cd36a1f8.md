---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/n-cd36a1f8
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/本地部署拓扑与回环绑定.md
  type: wiki
supersedes: []
tags:
- 部署模型
- 安全边界
- 部署
- 端口
- 回环
- docker
- 网络
- 拓扑
tier: canonical
title: 本地部署拓扑与回环绑定
updated_at: '2026-11-18T07:26:22Z'
---

> 四服务分布在不同端口，多数绑定 127.0.0.1；部署形态为单机 Docker + 宿主机进程。 2026-11-10 复核显示 Proxy 绑定 0.0.0.0、Magpie 含 LAN，容器内访问宿主须用 host.docker.internal；同日补充 stdio MCP 作为客户端子进程不监听端口，回连 127.0.0.1:8424/8125。

# 定义

[[TencentDB Agent Memory]] 的本地部署形态：单机 Docker 上运行多个服务，通常记作四个逻辑服务（[[Memory Proxy]]、[[Memory Hub]]、[[Memory Core]]、[[Memory Knowledge]]），各服务监听不同端口；另可有宿主机常驻进程 [[Magpie]]，以及由客户端拉起的非监听型 [[Team Brain MCP]]。

旧记录称所有服务**仅绑定 127.0.0.1**（本机回环），不对外暴露；2026-11-10 复核后需修正：Hub/Core/Knowledge 仍为 `127.0.0.1`，但 Proxy 为 `0.0.0.0`，Magpie 为 `127.0.0.1 + LAN`。绑定方式总体上构成安全边界，但“全部仅回环、不对外暴露”的旧绝对表述已与复核结果冲突。同日补充：stdio MCP 不监听任何端口，不参与端口绑定统计，但会主动回连本机回环端口。

# 拓扑

| 服务 | 容器 / 进程 | 端口 | 绑定 | 作用 |
| --- | --- | --- | --- | --- |
| [[Memory Proxy]] | `tdai-proxy` | 8096 | `0.0.0.0` | 模型/能力代理，记忆注入入口；转发上游 `/v1/messages`（旧记录上游为 [[applesay 上游模型服务]]） |
| [[Memory Hub]] | `tdai-memory-hub` | 8125 | `127.0.0.1` | 面板 API（管理用）；面板、Wiki 与知识索引管理 |
| [[Memory Knowledge]] | `tdai-memory-hub` | 8424 | `127.0.0.1` | 知识索引（Wiki 检索） |
| [[Memory Core]] | `tdai-memory-core` | 8420 | `127.0.0.1` | 核心服务，SQLite + Docker 卷 `tdai-memory-core-data` |
| [[Magpie]] | 宿主机进程 `magpie.exe` | 3425 | `127.0.0.1 + LAN` | 统一模型网关 |
| [[Team Brain MCP]] | 客户端拉起的子进程 | 无（stdio） | 不监听 | 本地检索接入，回连 `127.0.0.1:8424` / `8125` |

> 注意：`tdai-memory-hub` **一个容器同时映射 8125 和 8424**。因此“三个容器”承载了四个逻辑服务；[[Magpie]] 则是额外的宿主机进程，[[Team Brain MCP]] 是非监听型客户端子进程。

```text
客户端(DSH/Codex) → 127.0.0.1:8096 Proxy → 上游
                         │                   ├─ 旧记录：https://applesay-api-hup.applesay.cn/v1
                         │                   └─ 级联时：host.docker.internal:3425 Magpie
                         ↓
                   Core(8420) / Knowledge(8424) ← Hub(8125) 管理
```

stdio MCP 构成一条平行于模型链的本地检索路径：

```text
Agent(DSH/Codex/Claude Code) → stdio MCP 子进程 → 127.0.0.1:8424 Knowledge / 8125 Hub → 8420 Core
```

## 旧描述与 2026-11-10 复核的差异

- 旧页称“四服务仅绑定 `127.0.0.1`，不对外暴露”。
- 新复核结果：[[Memory Proxy]] 绑定 `0.0.0.0`，[[Magpie]] 绑定 `127.0.0.1 + LAN`；仅 Hub、Core、Knowledge 保持 `127.0.0.1`。
- 因此，**“全部仅回环”不再成立**；“外部不可达”只对回环绑定的服务成立，8096 与 Magpie 的 LAN 暴露面需另行由防火墙/网络策略约束。
- [[Team Brain MCP]] 不监听端口，因此不属于上述端口绑定争议；但其回连目标均为 `127.0.0.1`。

# 非监听型组件：stdio MCP（2026-11-10 新增）

[[Team Brain MCP]] **不监听任何端口**，它是由客户端（[[DSH Desktop]] / [[Codex Desktop]] / Claude Code）拉起的**子进程**，以 MCP stdio 与客户端通信，再**主动回连**：

- `http://127.0.0.1:8424`（[[Memory Knowledge]] `/v3`，无密钥）
- `http://127.0.0.1:8125`（[[Memory Hub]] `/api/v1`，需 `sk-mem-` 密钥）

含义：

- 拓扑图上多一条**平行于模型链**的检索路径（`Agent → MCP → 8424/8125 → 8420`），不经过 8096。
- MCP 的可用性取决于**客户端能否拉起子进程**，而非任何端口的健康状态——Windows 上曾因入口判断失效而整体不可用（见 [[Windows ESM 入口判断失效]]）。
- 它不改变监听型服务的回环绑定结论，但说明“记忆访问入口”并非只有 Proxy 一个。

# 容器内回环与宿主可达性

「绑定 127.0.0.1」在**容器视角下不成立**——容器内的 `127.0.0.1` 是容器自己，打不到宿主机。实测从 `tdai-proxy` 容器内访问：

| 从 `tdai-proxy` 容器内访问 | 结果 |
| --- | --- |
| `http://host.docker.internal:3425/` | **200** ✅ |
| `http://127.0.0.1:3425/` | **000** ❌ |

**结论**：

1. 需要访问宿主机进程（[[Magpie]]）时，上游地址必须写 `host.docker.internal`。
2. `PROXY_UPSTREAM_URL` 末尾要带 `/v1`——[[Memory Proxy]] 的 `joinUrl` 只在 base 缺失路径时补 `/messages` 或 `/chat/completions`。
3. stdio MCP 的 `127.0.0.1` 回连是客户端/宿主机视角；容器内访问宿主仍须使用 `host.docker.internal`，不能套用 MCP 的回环地址。

# 意义

- **安全边界**：对回环绑定的 Hub/Core/Knowledge 而言，记忆数据与面板入口不出本机，外部不可达；但按 2026-11-10 复核，Proxy 的 `0.0.0.0` 与 Magpie 的 LAN 绑定属于例外，需要额外防护。
- **访问路径**：外部（非本机）客户端必须通过 8096 才能用上记忆；本机 Agent 还可通过 stdio MCP 走 8424/8125，其余回环端口仅本机可达。这也解释了为什么级联配置里会出现 `host.docker.internal` 这种“非本机地址”。
- **非监听型接入**：[[Team Brain MCP]] 不占端口，由客户端拉起子进程；其可用性取决于客户端入口与子进程拉起是否正常，而不是端口健康检查。
- **部署前置**：`start-local.sh` 依赖 Git Bash 与 Docker Desktop；仓库与本地配置分处 `TencentDB-Agent-Memory` 与 `TencentDB-Agent-Memory-local`。
- **持久化**：数据落在 Docker 卷 `tdai-memory-core-data`，容器重建不丢数据。
- 与 [[凭据分层模型]] 叠加，构成“本机访问 + 服务端持有上游凭据”的两层边界。
- 它也是 [[静默失效与健康检查盲区]] 中“挂载失败仍 healthy”得以发生的环境前提：容器活着，只是打不到正确上游；MCP 侧则表现为客户端子进程/入口失效。
- 与 [[级联代理拓扑与分层顺序]] 相关：级联时 Proxy 需经 `host.docker.internal:3425` 访问 Magpie。

# 相关实体

[[TencentDB Agent Memory]]、[[Memory Hub]]、[[Memory Core]]、[[Memory Knowledge]]、[[Memory Proxy]]、[[applesay 上游模型服务]]、[[Magpie]]、[[Team Brain MCP]]、[[DSH Desktop]]、[[Codex Desktop]]、[[凭据分层模型]]、[[静默失效与健康检查盲区]]、[[Windows ESM 入口判断失效]]、[[级联代理拓扑与分层顺序]]、[[start-proxy 启动脚本]]

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §2、§3.2、§5.1、§5.2
- `memory-hub-magpie-级联配置手册.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §3、§7

## stdio MCP 补充细节

- 回连目标由环境变量指定：`KNOWLEDGE_API_URL`（→ `127.0.0.1:8424`）与 `MEMORY_PANEL_URL`（→ `127.0.0.1:8125`）。
- **生命周期绑定宿主客户端**：DSH 重启则 MCP 子进程随之重启；不存在独立于客户端的进程守护。
- **多实例路由**：以 `TDAI_SERVICE_ID`（默认 `default`）选择目标实例，与面板 API 的 `x-tdai-service-id` 请求头一一对应。

相关：[[stdio MCP 分发与启动约束]]（子进程侧启动前提）、[[能力开关显式固化]]（拓扑正确但能力被关闭的情形）。
