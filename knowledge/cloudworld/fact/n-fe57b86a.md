---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-fe57b86a
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/绑定失败即整体失败.md
  type: wiki
supersedes: []
tags:
- 失败语义
- relay
- 启动过程
- 架构纠正
tier: canonical
title: 绑定失败即整体失败
updated_at: '2026-11-18T07:26:22Z'
---

> relay 启动为 all-or-nothing：bridge 绑定失败会连带释放主监听、进程退出，不存在「bridge 不可用但主链路降级可用」的形态。

# 定义

描述 [[cloud-world relay]] 启动过程的失败语义：`Relay::bind` 依次绑定主监听（`relay_port`）与 bridge 监听（`bridge_port`），**任一绑定返回错误即整体返回 `Err`**，进程退出；bridge 绑不上时，先建立的主监听也会一并释放。

因此系统不存在「bridge 挂了但主链路还能用」的降级形态——一旦 bridge 端口被占用，**模型请求完全不可用**。

# Significance

- 决定了端口冲突的**严重级别**：不是能力弱化，而是完全不可用，因此排查优先级高（见 [[端口占用排查流程]]）。
- 纠正了 `docs/architecture.md` 中曾写错的降级表述（2026-11-12 实测纠正），是架构文档失败语义表的定论依据。
- 引出对**可观测性**的要求：日志必须能区分「启动失败」与「端口占用降级」，否则会误导排障方向。

# 机制路径

1. `Relay::bind` 先绑 `relay_port`（默认 8787）。
2. 再绑 bridge `bridge_port`（默认 8096，必须 loopback）。
3. 任一步失败 → 返回 `RelayError::Bind`，Display 文案 `cannot bind relay listener at {address}`。
4. 进程退出 → 主监听释放 → 模型请求不可用。

# 已知缺陷

`RelayError::Bind` 的 Display 文案对主监听与 bridge **共用**，无法从错误信息判断是哪一处失败。临时应对：**以报错中的地址为准**——地址端口等于 bridge 端口，即为 bridge 冲突。

# Related Entities

- [[cloud-world relay]]：该语义的承载者。
- [[第三方 docker 栈（占用 0.0.0.0:8096）]]：触发该语义的常见外部原因。
- 相关概念：[[端口绑定共存模型]]、[[端口占用排查流程]]。

# Citations

- `crates/relay/src/lib.rs`：`Relay::bind`、`RelayError::Bind`
- `docs/architecture.md` §4.3.1、§5 失败语义表（2026-11-12 更正）
- 来源：[[03-bridge端口冲突语义]]
