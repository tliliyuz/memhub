---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/n-1bee4cfc
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/账号级默认会话资产记录.md
  type: wiki
supersedes: []
tags:
- 会话初始化
- 资产解析
- 账号配置
tier: canonical
title: 账号级默认会话资产记录
updated_at: '2026-11-18T07:26:22Z'
---

> 账号维度持久化的 team/agent/task 固化记录，一旦存在即成为资产解析链第一档，并压制请求头与交互表单。

# 定义

`user-session-default` 是按**账号维度**持久化的会话资产固化记录，保存该账号在新建会话时应默认采用的 team / agent / task。它存在即命中 [[资产解析优先级链]] 的第一档：新会话直接使用该记录，后两档（[[请求头预设]]、[[交互式资产选择表单]]）被完全跳过。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 记录标识 | `user-session-default` |
| 作用域 | 账号级（非单次会话级） |
| 写入接口 | `user-session-default/set`，由 [[资产服务]] 提供与校验 |
| 读取方 | [[会话初始化服务]]（`session/claude-code/init.ts` v3.3 分支） |
| 生效效果 | 命中后忽略 `x-team-id` / `x-agent-id` / `x-task-id` |
| 是否有开关 | 无单独开关；只能删除记录（见 [[账号默认资产恢复流程]]） |
| 删除方式 | `cloud-world asset unbind`（[[cloud-world CLI]]） |
| 查询方式 | `cloud-world asset default`，删除后应返回「未设置默认资产」 |

# 关系

- 是 [[资产解析优先级链]] 第一档的载体，与第二档 [[请求头预设]]、第三档 [[交互式资产选择表单]] 构成短路关系。
- 由 [[资产服务]] 负责读写与「成员关系 / agent 归属 / 可见性」校验，遵循 [[服务端权威校验]]。
- 由 [[会话初始化服务]] 在会话初始化时读取并优先采用。
- 存在动因见 [[非交互会话资产固化]]：非交互会话（`claude -p`）无法渲染表单。
- 删除它即恢复表单流程，见 [[账号默认资产恢复流程]]。

# 设计取舍

固化到账号级让非交互会话也能获得确定的 team/agent/task；代价是同一账号下的**交互会话也不再询问**用户。这一取舍是 [[预期行为 vs bug 判定]] 中「表单不出现 = 预期行为」的根因。

# Citations

- `crates/service/src/assets.rs`（`asset/list-accessible` 与默认资产读写）
- 服务端 `session/claude-code/init.ts` v3.3 分支
