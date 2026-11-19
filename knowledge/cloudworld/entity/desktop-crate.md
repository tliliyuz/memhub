---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/desktop-crate
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/desktop-crate.md
  type: wiki
supersedes: []
tags:
- 构建单元
- rust
- tauri
tier: canonical
title: desktop crate
updated_at: '2026-11-18T07:26:22Z'
---

> crates\desktop 是界面与 Rust 命令层的构建单元，含 src-tauri，日常迭代在此跑 npm run tauri dev。

# 定义

`crates\desktop` 是桌面端界面与 Rust 命令层的构建单元，内含 `src-tauri`（`tauri.conf.json`、`src/lib.rs`、`src/main.rs`）以及前端工程（`dist` 输出目录）。

它是 [[编译期前端嵌入]] 的实际发生地，也是 [[开发态迭代]] 的工作目录。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 主要子目录 | `src-tauri`（Tauri 配置与 Rust 代码）、前端源码与构建产物 `dist` |
| 日常开发命令 | `cd crates\desktop` 后 `npm run tauri dev` |
| 增量重编范围 | 日常改动只重编本 crate + 前端，几十秒到两分钟 |
| 构建输出 | 默认 `target\`；被占用时改用 `--target-dir target-build`，见 [[构建目录隔离]] |

# 关系

- 产出 [[cloud-world.exe]]。
- 依赖 [[Tauri 框架]] 提供的 `generate_context!`、`frontendDist`、`tauri dev`。
- 属于 [[打包分层模型]] 第一层（exe）的重编边界之内。

# Citations

- `crates/desktop/src-tauri/tauri.conf.json`
- `crates/desktop/src-tauri/src/lib.rs`
