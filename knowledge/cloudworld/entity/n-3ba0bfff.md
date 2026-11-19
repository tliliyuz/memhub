---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/n-3ba0bfff
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/交互式资产选择表单.md
  type: wiki
supersedes: []
tags:
- 会话初始化
- 交互界面
- 资产解析
tier: canonical
title: 交互式资产选择表单
updated_at: '2026-11-18T07:26:22Z'
---

> 新会话中渲染 team/agent/task 选择的交互界面，属资产解析链第三档兜底，非交互模式下不可用。

# 定义

交互式资产选择表单是新会话中让用户选择 team / agent / task 的界面，是 [[资产解析优先级链]] 的**第三档**（兜底档）：仅当前两档（[[账号级默认会话资产记录]]、[[请求头预设]]）均未命中时才会渲染。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 档位 | 第三档（兜底） |
| 出现条件 | 账号无默认资产，且请求头未指定 |
| 不可用场景 | 非交互会话（如 `claude -p`）无法渲染表单 |

# 关系

- 「表单不出现」的常见根因是 [[账号级默认会话资产记录]] 存在，见 [[预期行为 vs bug 判定]]。
- 恢复表单的唯一路径是删除账号级记录，见 [[账号默认资产恢复流程]]。
- 表单选项来源为 [[资产服务]] 的 `asset/list-accessible`。
- 其「在非交互模式下不可用」正是 [[非交互会话资产固化]] 设计存在的动因。
