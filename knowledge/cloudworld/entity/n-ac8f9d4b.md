---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/n-ac8f9d4b
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/会话初始化服务.md
  type: wiki
supersedes: []
tags:
- 会话初始化
- 服务端模块
- 资产解析
tier: canonical
title: 会话初始化服务
updated_at: '2026-11-18T07:26:22Z'
---

> 服务端会话初始化入口（session/claude-code/init.ts），v3.3 分支实现三级资产优先解析与请求头忽略行为。

# 定义

会话初始化服务是服务端新建会话时的初始化入口，实现位于 `session/claude-code/init.ts`。其 v3.3 分支负责解析本次会话使用的 team / agent / task，并按 [[资产解析优先级链]] 的三级顺序短路取值。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 代码位置 | `session/claude-code/init.ts` |
| 关键分支 | v3.3 分支（优先级解析实现） |
| 解析顺序 | 账号默认 → 请求头预设 → 交互表单 |
| 短路语义 | 命中 [[账号级默认会话资产记录]] 时，后两档（含请求头）完全跳过 |
| 总开关 | `sessionInit.enabled`（默认 `false`），控制整条初始化链路，见 [[会话初始化]] |

# 关系

- 读取 [[账号级默认会话资产记录]] 作为第一档输入。
- 在第一档未命中时消费 [[请求头预设]]（`x-team-id` / `x-agent-id` / `x-task-id`）。
- 前两档均未命中时依赖 [[交互式资产选择表单]] 兜底；非交互模式下该档不可用（见 [[非交互会话资产固化]]）。
- 与 [[资产服务]] 分工明确：本模块管**优先级解析**，[[资产服务]] 管**资产读写与校验**。

# 行为要点

- 「header 里指定了 agent 却不生效」由此处的优先级短路决定，属预期行为，见 [[预期行为 vs bug 判定]]。
- 没有针对第一档的独立开关；只能通过删除账号级记录恢复表单，见 [[账号默认资产恢复流程]]。

# Citations

- 服务端 `session/claude-code/init.ts` 的 v3.3 分支（优先级与 header 忽略行为）
- `docs/architecture.md` §4.2 约束 2
