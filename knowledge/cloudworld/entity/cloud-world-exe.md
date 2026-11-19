---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/cloud-world-exe
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-world-exe.md
  type: wiki
supersedes: []
tags:
- 二进制
- tauri
- 发布物
tier: canonical
title: cloud-world.exe
updated_at: '2026-11-18T07:26:22Z'
---

> 双角色二进制（GUI 界面 + relay 子命令），前端产物在编译期嵌入其中，因此任何代码改动都必须重编。

# 定义

`cloud-world.exe` 是桌面端唯一的产品二进制，承担双角色：

1. **GUI 界面进程** —— 启动窗口，加载编译期嵌入的前端产物。
2. **`relay` 子命令** —— 以 `--config-dir … relay --profile default` 形式被拉起为独立后台 relay 进程（见 [[relay 后台进程]]）。

它是 [[打包分层模型]] 中的最内层发布物：代码改动都要重编它。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 前端来源 | 编译期经 `generate_context!()` 嵌入 `frontendDist: "../dist"`，不从磁盘读取，见 [[编译期前端嵌入]] |
| 重编成本 | 首次 release 需过全部依赖（几分钟）；之后只重编 desktop crate + 前端（几十秒到两分钟） |
| `windows_subsystem` | `main.rs` 中 `windows_subsystem = "windows"` 仅非 debug 生效 |
| 生产实例路径 | watchdog 使用 `target\debug\cloud-world.exe` 维持生产 relay，该文件被文件锁占用 |
| 断开方式 | 界面点「断开」或执行 `cloud-world disconnect` 子命令 |

# debug 构建的可见副作用

`windows_subsystem = "windows"` 只在非 debug 时生效，所以 debug 版双击后会多一个黑色控制台窗口，关主窗口时它跟着走。这不是缺陷，但发给别人前要换成 release 构建。

# 关系

- 被 [[NSIS 安装包]] 包一层后对外分发；exe 变了安装包就得重出。
- 由 [[desktop crate]] 构建产出，依赖 [[Tauri 框架]] 的 `generate_context!` / `frontendDist` 机制。
- 其 `target\debug\` 实例被 [[watchdog 计划任务]] 占用，直接导致需要 [[构建目录隔离]]。
- 与界面拉起的 relay 争用同一 8787 端口，见 [[relay 单实例与端口互斥]]。

# Citations

- `crates/desktop/src-tauri/src/lib.rs`（双角色二进制、`windows_subsystem` 条件编译）
- `crates/desktop/src-tauri/tauri.conf.json`（`frontendDist: "../dist"`、nsis 目标）
