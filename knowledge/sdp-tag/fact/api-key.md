---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/api-key
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/api-key-鉴权权限模型.md
  type: wiki
supersedes: []
tags:
- 鉴权
- 权限
- 接口
tier: canonical
title: API Key 鉴权权限模型
updated_at: '2026-11-18T07:26:22Z'
---

> API Key 会话角色集合为空，故去掉类上的 @SaCheckRole，改由权限码承担，并由单测守护。

# 定义

[[图谱导出接口]] 等对外接口在 API Key 场景下的鉴权模型：

> 「API Key 会话的角色集合是空的，留角色校验会把服务端调用全部挡死。」

因此去掉类上的 `@SaCheckRole`，控制改由**权限码**承担；这些权限码没有进任何租户套餐。

# 守护方式

单测 `exportControllerIsOpenToApiKeyWithRegisteredPermissions`，断言类上没有角色校验。

# 意义

「角色校验」与「机器对机器调用」语义不兼容：机器会话没有角色，只有权限码。把校验放在权限码上是正确的抽象层。

# 关联

- 相关实体：[[图谱导出接口]]
- 相关概念：[[裸契约信封]]、[[应用层模块化单体、部署层云原生]]

# Citations

- `02-方案选型与权衡.md` §26
