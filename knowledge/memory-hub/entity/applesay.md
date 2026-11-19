---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: memory-hub/entity/applesay
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/applesay-上游模型服务.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 模型服务
- 上游模型
- 上游
- deepseek
tier: canonical
title: applesay 上游模型服务
updated_at: '2026-11-18T07:26:22Z'
---

> 地址 https://applesay-api-hup.applesay.cn/v1 的上游模型服务，提供 deepseek-v4.1-flash-1017 等模型，凭据由服务端持有而非下发给客户端；2026-11-10 起从 [[Memory Proxy]] 的直连上游变为经 [[Magpie]] 转发的下游 provider 之一。

# 定义

applesay 上游模型服务是地址为 `https://applesay-api-hup.applesay.cn/v1` 的真实上游模型服务，提供 `deepseek-v4.1-flash-1017` 等模型，为 [[TencentDB Agent Memory]] 与 [[Memory Proxy]] 提供模型推理能力；同时也是 [[Magpie]] 的下游 provider 之一。

凭据由服务端持有，不下发给客户端（见 [[凭据分层模型]]）。

# 关键属性

| 属性 | 值 |
| --- | --- |
| Base URL / 地址 / 基址 | `https://applesay-api-hup.applesay.cn/v1` |
| 模型 / 代表模型 | `deepseek-v4.1-flash-1017` 等 |
| 凭据归属 | 服务端持有（不下发给客户端）；客户端只持有 `sk-mem-` 用户密钥 |
| 兼容接口 | `/v1/messages`（被 [[Memory Proxy]] 转发） |
| 接入位置（2026-11-10 后） | 经 [[Magpie]] 转发的下游 provider 之一 |

# 上游路径的变更

| 时间 | [[Memory Proxy]] 的上游 |
| --- | --- |
| 2026-11-10 之前 | 直连 applesay |
| 2026-11-10 起 | 经 [[Magpie]]（`http://host.docker.internal:3425/v1`），applesay 降为 Magpie 的下游 provider 之一 |

两条路径并存于历史记录中，属于时间点先后关系而非事实冲突，见 [[级联代理拓扑与分层顺序]] 与源页 [[Memory Hub × Magpie 级联配置手册]]。

# 与模型命名的关系

`deepseek-v4.1-flash` 族是该服务的真实落点之一，在 [[Magpie]] 的 `/v1/models` 中可经两种写法命中：

- `provider/model`（如 `trae-cn/deepseek-v4.1-flash`，落点确定）
- `auto/model`（如 `auto/deepseek-v4.1-flash`，路由组兜底）

`deepseek-v4.1-flash-1017` 这类带后缀的写法并非显式登记名，只是前缀匹配的副作用。详见 [[模型 ID 解析与路由组]]。

注：这与 [[DSH Desktop]] 配置中“模型名需填 `deepseek-v4.1-flash-1017`”的记录并不矛盾——前者是客户端填写/调用名，后者是 Magpie `/v1/models` 的登记与解析语义；带后缀写法依赖前缀匹配。

# 关系

- 与 [[Memory Proxy]]：被转发调用的下游（Proxy → 上游）；2026-11-10 之前为直连，之后经 [[Magpie]] 中转。
- 被 [[Magpie]] 路由调用（作为其下游 provider 之一）。
- 调用链上游：[[级联代理拓扑与分层顺序]]（客户端 → [[Memory Proxy]] → [[Magpie]] → 本服务）。
- 所属平台：[[TencentDB Agent Memory]]。
- 与 [[凭据分层模型]]：客户端只持有 Memory 的 `user_key`，模型凭据止于服务端。
- 与 [[DSH Desktop]]：模型名需填 `deepseek-v4.1-flash-1017`；旧名 `deepseek-flash` 曾被上游拒绝。
- 与 [[Proxy 转发故障分段定位]]：502 故障段位于 Proxy → 该上游；容器内无凭据探测可快速收到预期 401，仅证明探测当时可达。注：该结论基于直连时期的定位记录，2026-11-10 之后同一故障段已包含 [[Magpie]] 一跳。
- 与 [[applesay 团队]] 命名空间相关。
- 记忆归属项目：[[SDP Tag 项目]]。

# Citations

- `tencentdb-agent-memory-session.md`
- `memhub-magpie-级联配置手册.md` §1、§4.8
- `tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md`
- `模型-id-解析与路由组.md`
