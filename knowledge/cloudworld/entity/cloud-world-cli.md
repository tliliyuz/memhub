---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/cloud-world-cli
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-world-cli.md
  type: wiki
supersedes: []
tags:
- 命令行工具
- 运维
- 资产
tier: canonical
title: cloud-world CLI
updated_at: '2026-11-18T07:26:22Z'
---

> 用户与运维侧命令行工具，通过 asset unbind 删除账号默认资产、通过 asset default 查询当前默认资产。

# 定义

cloud-world CLI 是面向用户/运维的命令行工具，用于查看与清理与 [[账号级默认会话资产记录]] 相关的账号级状态。

# 关键命令

| 命令 | 作用 | 备注 |
| --- | --- | --- |
| `cloud-world asset unbind` | 删除账号级默认会话资产记录 | 恢复 [[交互式资产选择表单]] 的唯一手段 |
| `cloud-world asset default` | 查询当前账号默认资产 | 返回「未设置默认资产」即表示已删除 |

# 关系

- 操作对象是 [[账号级默认会话资产记录]]。
- 是 [[账号默认资产恢复流程]] 的执行载体。
- 底层数据与校验由 [[资产服务]] 提供。
- 不提供「关闭优先级某一档」的命令，因为该档本无单独开关（见 [[资产解析优先级链]] 与 [[会话初始化]]）。

# Examples

```bash
# 查看是否有账号默认资产（返回「未设置默认资产」= 无）
cloud-world asset default

# 删除账号默认资产，恢复新会话的资产选择表单
cloud-world asset unbind
```
