---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/compile-time-frontend-embedding
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/other/compile-time-frontend-embedding.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: compile-time-frontend-embedding
updated_at: '2026-11-18T07:26:22Z'
---

# 定义

Tauri 在编译期通过 `generate_context!()` 读取 `tauri.conf.json` 中的 `frontendDist: "../dist"`，把前端构建产物内联进二进制。运行时窗口加载的是 exe 内的资源，而不是磁盘上的 `dist` 目录。

# Significance

- 直接决定重编边界：`.tsx` / `.css` 改动、Rust 命令层改动、service 逻辑改动都落在 exe 层，必须重编；改一行 CSS 也要重编。
- 是 [[打包分层模型]] 中「exe 层」的判定依据。
- 与 [[开发态迭代]] 互补：在开发态靠 `tauri dev` 规避重编成本，成本只落在发版。

# 被否决的替代方案

「让窗口加载远端 URL、热更前端」看似可以绕开重编，但与 CSP `default-src 'self'` 和「不依赖网络也能用」的产品定位冲突，故不采用，见 [[离线优先与 CSP 约束]]。

# Related Entities

- [[Tauri 框架]]（`generate_context!`、`frontendDist`）
- [[desktop crate]]（构建单元，`src-tauri` 所在）
- [[cloud-world.exe]]（嵌入结果的载体）

# Citations

- `crates/desktop/src-tauri/tauri.conf.json`（`frontendDist: "../dist"`）
- `crates/desktop/src-tauri/src/lib.rs`
