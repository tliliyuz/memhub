---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/n-79abf11a
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/凭据分层模型.md
  type: wiki
supersedes: []
tags:
- 权限模型
- 凭据
- 安全
- 信任边界
- 网关
- sk-mem
- mcp
tier: canonical
title: 凭据分层模型
updated_at: '2026-11-18T07:26:22Z'
---

> 客户端只持有 Memory 平台的 user_key（sk-mem-），上游模型凭据仅由服务端持有，形成两段式信任边界；Magpie 的密钥替换行为从反向证明「密钥归属决定调用方向」，MCP 通过 MEMORY_USER_KEY 将 user_key 下发到子进程 env，是该边界的又一处落点。

# 定义

凭据分层模型指系统中存在两级互不可替代、彼此不交叉的凭据：

| 层 | 凭据 | 持有方 | 授权范围 |
|---|---|---|---|
| 业务层 / 客户端层 | `sk-mem-...` 用户密钥（`user_key`） | AI 客户端 / agent 运行时（[[DSH Desktop]]、[[Codex Desktop]] 等） | 只读查询团队资产（面板 `/api/v1`，如 8125 的只读查询） |
| 上游层 / 服务端层 | 各模型供应商 API Key / [[applesay 上游模型服务]] 凭据 | 仅服务端（[[Memory Proxy]] / [[Magpie]]） | 调用上游模型 |

具体而言：

1. **客户端层**：AI 客户端（[[DSH Desktop]]、[[Codex Desktop]] 等）只填 [[TencentDB Agent Memory]] 的 `user_key`（`sk-mem-` 前缀）。
2. **服务端层**：上游模型凭据（[[applesay 上游模型服务]]）仅由服务端持有，不下发给客户端。

由此形成两段式信任边界：

```
客户端 ──(sk-mem- user_key)──> 8096 Memory Proxy ──(服务端持有的上游密钥)──> 上游模型服务
```

## `user_key` 的本地来源

本地部署下 `sk-mem-` 用户密钥有两处来源：

1. `TencentDB-Agent-Memory-local/.admin-key` 文件
2. 面板 → 账户页

# 意义

- 客户端无需也不应知道上游模型密钥，密钥泄露面被收敛到服务端。
- 客户端即使被完全读取，也拿不到上游模型凭据。
- 客户端配置因此极简：Base URL 指向 [[Memory Proxy]] + `user_key` + 模型名。
- 与 [[本地部署拓扑与回环绑定]] 叠加构成两段式信任边界：网络不可达 + 凭据不外发。
- 排障含义：容器内可用“无凭据探测”验证上游可达性（预期 401），同时不暴露真实凭据 → 见 [[Proxy 转发故障分段定位]]。
- 凭据分层不仅决定“谁能看到密钥”，还决定**调用链方向**：密钥归属方必须位于调用链的外侧。
- 这条边界同时决定了两件事：**调用方向**（谁能直连上游）与**凭据泄漏半径**（客户端失陷只丢 `user_key`）。
- 反向证明：[[Magpie]] 在转发时替换密钥的行为，说明「密钥归属决定调用方向」——凭据在哪一侧，调用就必须由那一侧发起。

# 密钥替换型网关（反证）

2026-11-10 的级联实践引入了一个强反例：[[Magpie]] 是**密钥替换**型网关——收到客户端的占位 token（如字面量 `magpie`）后会**替换**成自己 provider 配置里的真实密钥再发上游。

因此若把方向反过来（`DSH → Magpie → Memory Proxy`），Magpie 会拿它自己那几家的 key 去请求 8096，而 [[Memory Proxy]] 只认 `sk-mem-` 用户密钥：

**实测对照**

| 请求密钥 | 目标 | 结果 |
|---|---|---|
| `sk-mem-...`（memory 用户密钥） | 8096 | 200 ✅ |
| magpie 密钥 | 8096 | 401 `invalid user_key` ❌ |

这正是「[[Memory Proxy]] 必须在外层」的**第二条独立理由**（第一条是记忆归属，见 [[级联代理拓扑与分层顺序]]）。

该行为与凭据分层模型的预期不兼容，属于反例，不改变模型本身：反向串联不是配置问题而是模型问题，任何重试都无法绕过，只会在链路上多一层 401。

相关旁证：[[Magpie]] 的 `/v1/messages` 实测不校验入站密钥（不带 `authorization` 仍 200），说明其额度防护依赖自身 LAN key 策略，不能作为信任边界。

# MCP 场景的补充边界（2026-11-10）

[[Team Brain MCP]] 把 `sk-mem-` 用户密钥写进客户端配置（env `MEMORY_USER_KEY`），这与本模型一致而非违背：

- 该密钥**只能**用于面板 8125 的只读查询，泄漏面有限；
- 上游模型凭据仍只在服务端，MCP 也**不参与模型转发**（检索链与模型链平行，见 [[MCP 双后端只读接入]]）。
- 附带结论：无密钥时 [[Team Brain MCP]] 会**部分降级**（[[Chat Memory]] / [[Skill]] 不可用，[[Wiki]] 与[[代码图谱]]照常），说明两层凭据在功能上也是解耦的。

## 新落点：进入 MCP 进程 env

[[Team Brain MCP]] 把 `user_key` 经 **`MEMORY_USER_KEY`** 下发到自己的**子进程环境变量**，再以 `x-tdai-user-key` 头调用 [[Memory Hub]] 8125 的 `/api/v1`。

由此推论：

- MCP 是**用户身份的承载者**，不是新的信任节点——它只转发 `user_key`，不持有任何上游模型凭据。
- 无 `MEMORY_USER_KEY` 时 [[Chat Memory]] / [[Skill]] 工具降级返回配置指引，而 [[Wiki]] / [[代码图谱]] 走 [[Memory Knowledge]] 的免密钥 `/v3` 端点照常工作 → 见 [[MCP 双后端只读接入]]、[[静默失效与健康检查盲区]]。
- `user_key` 出现在客户端配置文件中（`cordis.patch.yml` / `config.toml` / `settings.json`），因此**配置文件本身属于敏感物**。

# 实践约束

- Magpie 密钥从 Magpie 界面 / `~/.config/magpie/providers.json` 获取，**不写入 wiki**。
- `.env` 中的 `PROXY_UPSTREAM_API_KEY` 属于**服务端持有**的凭据，不随客户端分发。
- 面板 API 调用需要 `x-tdai-user-key`（`sk-mem-`），见 [[Memory Hub]]。
- `user_key` 可能出现在客户端配置文件中，配置文件本身应按敏感物管理。

# 相关实体

[[Memory Proxy]]、[[DSH Desktop]]、[[Codex Desktop]]、[[applesay 上游模型服务]]、[[Magpie]]、[[TencentDB Agent Memory]]、[[Memory Hub]]、[[Team Brain MCP]]、[[Memory Knowledge]]、[[Chat Memory]]、[[Skill]]、[[Wiki]]、[[代码图谱]]

# 相关概念

- [[能力开关显式固化]] —— 与「凭据正确但能力关闭」并列的失效面
- [[静默失效与健康检查盲区]] —— 降级路径的观测盲区

# 常见话题

- 权限模型 / 信任边界
- MCP 接入：见 [[MCP 双后端只读接入]]
- 部署模型：见 [[本地部署拓扑与回环绑定]]

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §4.6、§4.7
- `memory-hub-magpie-级联配置手册.md`
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `team-brain-mcp-接入指南.md` §2、§6、§7

> 来源文件名说明：旧页引用 `memhub-magpie-级联配置手册.md`，新页引用 `memory-hub-magpie-级联配置手册.md`；两者文件名不同，均予保留，待核实是否为同一手册的命名差异。
