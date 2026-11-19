---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/cloud-world
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-world-桌面端.md
  type: wiki
supersedes: []
tags:
- 桌面端
- tauri
- 交付物
- 验收
tier: canonical
title: cloud-world 桌面端
updated_at: '2026-11-18T07:26:22Z'
---

> cloud-world 项目的桌面端交付物，本次验收的被测对象，承载构建、测试、诊断、资产与全部未做项。

# cloud-world 桌面端

## 定义

cloud-world 项目的桌面端交付物（基于 tauri 打包），是 2026-11-12 验收的被测对象。它依赖 [[本地 relay]] 作为运行期的本地进程，并通过 [[真实请求链路]] 验证端到端连通性。

## 关键属性

- 技术栈：Rust workspace（core / api / relay / service / cli / desktop）+ 前端（`tsc --noEmit` + `vite build`）。
- 构建：`cargo build` 无警告；调试运行方式为 `--no-bundle --debug`。
- 前端产物：242 kB JS / 75 kB gzip。
- 资产：85 条可见，默认资产与 CLI 一致。
- 诊断：分级 `ok / warn / fail`；隔离 profile 为 `ok 13 / warn 5 / fail 0`，生产为 `ok 16 / warn 2 / fail 0`。
- 命令行开关：`--config-dir` / `--claude-dir`（仅环境变量可用，界面无入口）。
- 打包：`tauri.conf.json` 中定义了 nsis 目标与图标，但未走过正式打包流程。

## 测试分布

`cargo test --workspace` 共 **73 passed, 0 failed**（详见 [[实测口径]]）：

| crate | 数量 |
| --- | --- |
| core | 29 |
| api | 14 |
| relay | 5 |
| relay 集成测试 | 16 |
| service | 5 |
| cli | 2 |
| desktop | 2 |

## 关系

- 依赖 [[本地 relay]]：运行期的本地依赖进程，验收结束后需用 `status` 确认其仍在运行、bridge 端口正常。
- 通过 [[真实请求链路]] 获得端到端连通性证据。
- 验收实践主体，遵循 [[验收证据分层]]。
- 数值归属载体受 [[实测口径]] 约束。

## 未做项（截至 2026-11-12）

1. 未产出 NSIS 安装包（部署模型尚未验证）。
2. 只在 Windows 实测；`DETACHED_PROCESS` 的 macOS/Linux 等价路径未验证。
3. 界面不提供 `--config-dir` / `--claude-dir` 入口。
4. `clippy` 不可用，无 lint 结论。

# Citations

- [[08-验收证据分层]]（原始数值见 `docs/evidence/2026-11-12-desktop.md`）
