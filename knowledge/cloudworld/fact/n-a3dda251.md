---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-a3dda251
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/界面门槛与鉴权分离.md
  type: wiki
supersedes: []
tags:
- 桌面端
- 登录
- 鉴权
- 门禁
tier: canonical
title: 界面门槛与鉴权分离
updated_at: '2026-11-18T07:26:22Z'
---

> 进入主视图与通过鉴权是两件事——只有点「连接」才真正校验；「直接进来了」意味着本机早已登录过。

# 界面门槛与鉴权分离

## Definition

界面门槛与鉴权分离是指：界面是否进入主视图，与是否通过鉴权，是两条独立的判定。进入主视图**不代表**已经过鉴权；只有在用户点「连接」时才会真正校验凭据。

## Significance

- 消除「跳过登录」的误解：应用「直接进来了」不是绕过校验，而是**这台机器早就登录过**——`config.toml` 里有 profile，[[系统凭据库]] 里有对应 key，界面判定「已配置」直接进主视图。
- 让 UI 流程不必承担安全职责，安全由 [[凭据边界]] 保证。

## Related Entities

- [[桌面登录门禁]] — 本概念的直接实现证据（判定表达式）。
- [[桌面登录入参]] — 提供 `has_user_key`，决定 `prefill` 分支。
- [[系统凭据库]] — 鉴权真正依赖的状态源。

## Common Topics

- **模块边界**：UI 侧只做「是否显示登录页」的展示决策；校验逻辑在后端与凭据层。
- **权限模型**：与 [[凭据边界]] 一致——能否连接才是硬门槛。

## Examples

- 首次运行：`config_exists == false` → 进入 LoginView。
- 无 profile：`env.profiles.length === 0` → 进入 LoginView。
- 有 profile 但缺 key：`prefill` 为真 → 登录页预填方式打开，只补 key。
- 有 profile 且有 key：直接进主视图，但连接时仍要校验。
