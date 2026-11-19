---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-a2abe6a4
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/自动注册语义.md
  type: wiki
supersedes: []
tags:
- memhub
- 鉴权
- 副作用
tier: canonical
title: 自动注册语义
updated_at: '2026-11-18T07:26:22Z'
---

> user-key/login 对未知 key 自动建号，属有副作用的调用，需显式同意后才可触发。

# Definition

[[auth-user-key-login 端点]]（`POST /api/v1/auth/user-key/login`）在收到**未知 [[user_key]]** 时会自动创建账号并返回登录态，而不是返回「不存在」错误。

# Significance

- **这是写操作**：任何「先试试这个 key 能不能用」的探测如果打到该端点，都会产生脏账号。
- **正确分工**：
  - 需要「校验 key 是否有效」→ 用 [[meta-auth-verify 端点]]（只读，返回 `valid=false`，见 [[无效凭据语义分裂]]）。
  - 需要「用 key 换登录态」→ 才用 login 端点，并且应作为**用户明确同意**后的显式动作。
- **CLI / 自动化风险**：脚本化批量校验若误用 login，会静默注册大量账号；应将 login 封装为需要显式 flag 的动作。

# Related Entities

- [[auth-user-key-login 端点]]、[[meta-auth-verify 端点]]、[[user_key]]、[[凭据安全处理实践]]

# Common Topics

- 权限模型：读写语义分离，探测类操作必须无副作用。
- 系统架构：副作用调用在客户端 API 层应显式命名（如 `login_or_register`），避免被误当查询。
