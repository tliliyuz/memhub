---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/watchdog
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/watchdog-计划任务.md
  type: wiki
supersedes: []
tags:
- 运维
- powershell
- 计划任务
tier: canonical
title: watchdog 计划任务
updated_at: '2026-11-18T07:26:22Z'
---

> scripts/memhub-tunnel-watchdog.ps1 长期占用 target\debug\cloud-world.exe 维持生产 relay，是构建目录隔离的直接动因。

# 定义

watchdog 计划任务由 `scripts/memhub-tunnel-watchdog.ps1` 实现，负责长期维持生产 relay 进程：定期检查并按需以 `--profile default` 拉起 [[relay 后台进程]]。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 脚本路径 | `scripts/memhub-tunnel-watchdog.ps1` |
| 拉起的二进制 | `$relayExe` 指向 `target\debug\cloud-world.exe` |
| 拉起参数 | `--config-dir … relay --profile default` |
| 副作用 | 长期持有该 exe 的文件锁，使普通 `cargo build` 失败或替换生产二进制 |
| 端口占用 | 与界面拉起的 relay 争 8787 端口 |

# 关系

- 维持 [[relay 后台进程]] 的生产实例。
- 其对 `target\debug\cloud-world.exe` 的占用是 [[构建目录隔离]]（`--target-dir target-build`）的直接动因。
- 与界面 relay 的冲突见 [[relay 单实例与端口互斥]]。

# Citations

- `scripts/memhub-tunnel-watchdog.ps1`（`$relayExe` 指向 `target\debug\cloud-world.exe`）
- `docs/evidence/2026-11-12-desktop.md`
