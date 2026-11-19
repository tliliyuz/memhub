---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/brand-key
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/按-brand-路由-key.md
  type: wiki
supersedes: []
tags:
- 回调
- 路由
- 多租户
tier: canonical
title: 按 brand 路由 key
updated_at: '2026-11-18T07:26:22Z'
---

> 按载荷 brand 取对应回调 key，查不到就跳过回写并打 ERROR，绝不回落默认 key。

# 定义

载荷里的 `brand` 原样带过来，按 brand 取对应的回调 key；查不到就**跳过回写并打 ERROR**。

# 为什么不能回落

> 「查不到 key 就回落默认 key，等于把别家数据写进 ZARA 的 tenant 235——**这比不回写更糟**。」

数据错投到别的租户是不可逆的合规问题；不回写只是丢一次回调，可重放修复。

# 状态

方案已定，**未落地**。

# 关联

- 相关实体：[[ZARA 租户]]、[[回调服务]]
- 相关概念：[[回调配置分层]]

# Citations

- `02-方案选型与权衡.md` §17
