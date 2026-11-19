---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/03-bridge
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/sources/03-bridge-端口冲突语义.md
  type: wiki
supersedes: []
tags:
- relay
- 端口绑定
- 失败语义
- 运维
- 决策记录
tier: canonical
title: 03-bridge端口冲突语义
updated_at: '2026-11-18T07:26:22Z'
---

> 实测纠正「bridge 端口被占用只是降级」的错误语义：bridge 绑定失败会导致 relay 整体启动失败、主监听一并释放，并给出与第三方 docker 栈争用 8096 的共存矩阵与排查流程。

# 摘要

本文档是对既有架构文档中一条错误失败语义的**实测纠正与定论**（2026-11-12）。曾写错的表述是「bridge 不可用但主链路降级可用」；实测结论是：`bridge_port` 被其他进程占用时，[[cloud-world relay]] 进程**直接退出**，模型请求一并不可用，不存在部分能力保留的降级形态。

# 核心结论

- **绑定失败即整体失败**：relay 的启动是 all-or-nothing，见 [[绑定失败即整体失败]]。
- **冲突纯属本机端口撞车**：与服务端配方 `injection.externalGatewayUrl` 无关，该配置指向服务器自身的 loopback，属于被明确排除的误判方向。
- **同一次冲突在不同机器上表现可能不同**：取决于对方进程的绑定独占性，见 [[端口绑定共存模型]]。
- **现有错误文案无法定位失败点**：主监听与 bridge 共用文案，排查须先看报错地址，见 [[端口占用排查流程]]。

# 机制

`Relay::bind` 的绑定顺序为：先绑主监听（`relay_port`，默认 8787），再绑 bridge（`bridge_port`，默认 8096）。**任一绑定失败即整体返回 `Err`**。因此 bridge 绑不上 → 进程退出 → 主监听一并释放，模型请求完全不可用。

副作用：两处失败共用同一条错误文案 `cannot bind relay listener at {address}`，看起来总像主监听的问题。**排查时以报出的地址为准**——地址端口等于 bridge 端口时，就是 bridge 冲突。

# 与第三方 docker 栈争用 8096（实测共存矩阵）

场景：本机已有另一套 docker 栈监听 `0.0.0.0:8096`，而 cloud-world 的 relay 需要监听 `127.0.0.1:8096`。两者是**不同的两个程序**——cloud-world 是客户端 relay，docker 栈是无关的第三方服务（见 [[第三方 docker 栈（占用 0.0.0.0:8096）]]）。

| 第三方的绑定方式 | 结果 |
| --- | --- |
| `0.0.0.0:8096` 非独占 | relay 的 `127.0.0.1:8096` 绑定成功，两者并存；发往 loopback 的请求由 relay 的 bridge 应答（更具体的地址优先） |
| `0.0.0.0:8096` 独占（`SO_EXCLUSIVEADDRUSE`） | relay 的 loopback 绑定失败（`os error 10013`），relay 起不来 |
| 已有进程占住 `127.0.0.1:8096` | 绑定失败，relay 起不来 |

完整模型与跨机器差异见 [[端口绑定共存模型]]。

# 运维含义

- 「启动失败」与「端口占用降级」在日志里形似但后果差别巨大（完全不可用 vs 部分能力弱化），**错误文案需要能区分两者**——当前不能，属已记录缺陷（`RelayError::Bind` 的 Display 文案对主监听与 bridge 共用）。
- 排查顺序：`Get-NetTCPConnection -LocalPort <port>` 找占用者 → 确认对方绑定的独占性 → 再决定改端口还是停对方，详见 [[端口占用排查流程]]。

# Citations

- `crates/relay/src/lib.rs`：`Relay::bind`（先主监听后 bridge，任一失败返回 `Err`）与 `RelayError::Bind` 文案
- `crates/core/src/config.rs`：`DEFAULT_BRIDGE_PORT = 8096`、`DEFAULT_RELAY_PORT = 8787`；bridge 必须为 loopback，且不得与 relay 端口相同
- `docs/architecture.md` §4.3.1 与 §5 失败语义表（2026-11-12 更正）

# 相关页面

- 实体：[[cloud-world relay]]、[[第三方 docker 栈（占用 0.0.0.0:8096）]]
- 概念：[[绑定失败即整体失败]]、[[端口绑定共存模型]]、[[端口占用排查流程]]
