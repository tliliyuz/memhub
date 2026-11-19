---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/csp
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/离线优先与-csp-约束.md
  type: wiki
supersedes: []
tags:
- 安全
- csp
- 可用性
- 架构决策
tier: canonical
title: 离线优先与 CSP 约束
updated_at: '2026-11-18T07:26:22Z'
---

> 拒绝「窗口加载远端 URL 热更前端」：与 default-src 'self' 冲突，且产品要求不依赖网络，属安全性与可用性双重倒退。

# 定义

本项目的两条硬约束共同否决了「前端放服务器、窗口加载远端 URL 热更」的方案：

1. **CSP 约束**：当前 CSP 为 `default-src 'self'`，加载远端 URL 与策略冲突。
2. **离线优先**：产品定位要求「不依赖网络也能用」；域名备案问题已经证明网络不可依赖。

# Significance

- 热更前端虽然能省掉重编 exe，但会同时牺牲安全性（放开 CSP）与可用性（依赖网络），属双重倒退，因此不接受。
- 反过来强化了 [[编译期前端嵌入]] 的合理性：前端内联在 [[cloud-world.exe]] 中是「离线可用 + 严格 CSP」的自然结果。
- 使 [[打包分层模型]] 的 exe 层不可被热更绕过，发版流程必须完整（含 [[NSIS 安装包]] 重出）。

# 决策记录

| 方案 | 结论 | 理由 |
| --- | --- | --- |
| 远端 URL 热更前端 | 不采用 | 与 `default-src 'self'` 冲突；依赖网络 |
| 编译期嵌入前端 + 发版重编 | 采用 | 离线可用、CSP 收紧 |

# Related Entities

- [[Tauri 框架]]（CSP 配置）
- [[compile-time-frontend-embedding|编译期前端嵌入]]

# Citations

- `crates/desktop/src-tauri/tauri.conf.json`
