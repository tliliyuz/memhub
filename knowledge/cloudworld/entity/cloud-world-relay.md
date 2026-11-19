---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloudworld/entity/cloud-world-relay
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-world-relay.md
  type: wiki
supersedes: []
tags:
- relay
- 客户端
- 端口绑定
tier: canonical
title: cloud-world relay
updated_at: '2026-11-18T07:26:22Z'
---

> 运行在客户端的 relay 服务进程，同时监听 relay_port(8787) 与 loopback 上的 bridge_port(8096)，任一绑定失败即整体启动失败退出。

# 定义

cloud-world relay 是运行于**客户端**的 relay 服务进程，负责对外提供主监听（`relay_port`）并同时在本机 loopback 上开一个 bridge 监听（`bridge_port`），用来接住注入的 curl 请求。它启动时采用 all-or-nothing 语义：任意一个监听绑定失败，进程即退出。

# Key Attributes

| 属性 | 值 / 说明 |
| --- | --- |
| 主监听端口 | `relay_port`，默认 `8787`（`DEFAULT_RELAY_PORT`） |
| bridge 端口 | `bridge_port`，默认 `8096`（`DEFAULT_BRIDGE_PORT`） |
| 绑定顺序 | `Relay::bind` 先绑 `relay_port`，再绑 `bridge_port`；**任一失败整体返回 `Err`** |
| 绑定地址约束 | bridge 必须绑定 loopback；且 bridge 端口不得与 relay 端口相同（`crates/core/src/config.rs`） |
| 失败后果 | 进程退出，主监听一并释放，模型请求完全不可用（见 [[绑定失败即整体失败]]） |
| 错误类型 | `RelayError::Bind`，Display 文案为 `cannot bind relay listener at {address}`，主监听与 bridge **共用**，无法从文案区分失败点（已记录缺陷） |

## bridge 监听端点

relay 内部用于接住注入 curl 请求的 loopback 监听。默认端口 8096，必须为 loopback 地址；其身份依附于 relay 进程本身（不是独立服务），因此不单独建页。当本机 8096 已被占用时：
- 对方为非独占通配绑定（`0.0.0.0:8096`）→ 本端点仍可绑定成功，更具体的 loopback 地址优先应答；
- 对方为独占绑定（`SO_EXCLUSIVEADDRUSE`）或已占住 `127.0.0.1:8096` → 绑定失败（`os error 10013`），relay 起不来。

详见 [[端口绑定共存模型]]。

# Relationships

- 自身包含 [[cloud-world relay#bridge 监听端点]] 能力：与 bridge 端口配置约束强绑定（见上文 Key Attributes）。
- 与 [[第三方 docker 栈（占用 0.0.0.0:8096）]]：**不同程序、无依赖**，仅可能在本机 8096 端口上发生撞车。
- 与服务端配方 `injection.externalGatewayUrl`：**无关**。该配置指向服务器自己的 loopback，客户端占用 8096 只是为了接住注入的 curl 请求，冲突纯属本机端口撞车，不要顺着服务端配置排查。
- 启动语义由 [[绑定失败即整体失败]] 定义；冲突复现条件见 [[端口绑定共存模型]]；现场处置见 [[端口占用排查流程]]。

# Citations

- `crates/relay/src/lib.rs`：`Relay::bind`、`RelayError::Bind`
- `crates/core/src/config.rs`：`DEFAULT_BRIDGE_PORT`、`DEFAULT_RELAY_PORT` 与 loopback 约束
- `docs/architecture.md` §4.3.1、§5 失败语义表（2026-11-12 更正）
- 来源：[[03-bridge端口冲突语义]]
