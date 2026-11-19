---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/relay
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/relay-单实例与端口互斥.md
  type: wiki
supersedes: []
tags:
- relay
- 端口
- 运维
tier: canonical
title: relay 单实例与端口互斥
updated_at: '2026-11-18T07:26:22Z'
---

> 生产 relay 与界面拉起的 relay 争同一 8787 端口；界面检测到已有 relay 就不拉起（正确），但从界面「断开」会连生产 relay 一起停掉。

# 定义

同一台机器上同时只能有一套 relay 运行，因为生产实例与界面实例监听同一个 8787 端口。

| 场景 | 行为 | 评价 |
| --- | --- | --- |
| 端口已有 relay，界面启动 | 不再拉起新 relay | 正确 |
| 界面点击「断开」 | 会把生产 relay 一起停掉 | 风险点：误停生产 |
| 需要真正断开 | 界面「断开」或 `cloud-world disconnect` | 显式操作 |
| 关闭窗口 | 不断连（relay 是独立后台进程） | 预期行为 |

# Significance

- 解释了「关窗口不断连」的反直觉现象：[[relay 后台进程]] 生命周期与窗口解耦。
- 提示运维风险：在装有生产 relay 的机器上从界面点「断开」，会中断生产服务。
- 与 [[构建目录隔离]] 同属「开发/调试与生产共存于一台机器」的约束集合。

# Related Entities

- [[relay 后台进程]]、[[cloud-world.exe]]（`disconnect` 子命令）、[[watchdog 计划任务]]、[[运行期配置文件 config.toml]]（端口来源）

# Citations

- `scripts/memhub-tunnel-watchdog.ps1`
- `docs/evidence/2026-11-12-desktop.md`
