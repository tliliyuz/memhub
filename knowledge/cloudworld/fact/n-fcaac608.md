---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-fcaac608
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/会话初始化.md
  type: wiki
supersedes: []
tags:
- 会话初始化
- 配置开关
tier: canonical
title: 会话初始化
updated_at: '2026-11-18T07:26:22Z'
---

> 服务端新建会话时的初始化链路，包含三级资产优先解析，仅由 sessionInit.enabled 一个总闸控制（默认 false）。

# 定义

会话初始化是服务端处理新会话建立时的整体链路，负责确定本次会话的 team / agent / task 等资产上下文。本页记录该链路的整体性与唯一的配置开关。

# 配置项

| 配置项 | 默认值 | 作用范围 | 常见误解 |
| --- | --- | --- | --- |
| `sessionInit.enabled` | `false` | **整条**会话初始化链路的总闸 | 误以为可用它单独关闭「账号默认」这一档 |

关闭 `sessionInit.enabled` 等于整条初始化都不执行，**不能**用于恢复 [[交互式资产选择表单]]；恢复表单应走 [[账号默认资产恢复流程]]。

# 与优先级的关系

[[资产解析优先级链]] 内部没有分档开关：第一档 [[账号级默认会话资产记录]] 无法被单独禁用，只能被删除。这是「搜遍配置找不到开关」的直接原因，见 [[预期行为 vs bug 判定]]。

# 相关页面

- [[会话初始化服务]]：链路的实现模块。
- [[资产服务]]：链路所需的资产数据来源。
