---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/tauri
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/tauri-框架.md
  type: wiki
supersedes: []
tags:
- 框架
- 桌面端
tier: canonical
title: Tauri 框架
updated_at: '2026-11-18T07:26:22Z'
---

> 提供 generate_context!、frontendDist、tauri dev、CSP 与 windows_subsystem 条件编译等机制的桌面应用框架。

# 定义

Tauri 是桌面应用框架，[[cloud-world.exe]] 与 [[desktop crate]] 建立在其机制之上。它决定了本项目的重编边界与开发体验。

# 关键属性（本文涉及的机制）

| 机制 | 在本文中的作用 |
| --- | --- |
| `generate_context!()` + `frontendDist: "../dist"` | 编译期把前端产物嵌入 exe，见 [[编译期前端嵌入]] |
| `tauri dev` | 前端热更新 + Rust 自动重编重启，见 [[开发态迭代]] |
| CSP（`default-src 'self'`） | 阻止窗口加载远端 URL 热更前端，见 [[离线优先与 CSP 约束]] |
| NSIS 打包目标 + `version` | 生成 [[NSIS 安装包]]，版本号须同步升 |
| `windows_subsystem` 条件编译 | 仅非 debug 生效，debug 版多一个控制台窗口 |

# 关系

- 被 [[desktop crate]] 使用并产出 [[cloud-world.exe]]。
- 其 CSP 与前端嵌入机制共同否决了「远端热更前端」方案。

# Citations

- `crates/desktop/src-tauri/tauri.conf.json`
- `crates/desktop/src-tauri/src/lib.rs`
