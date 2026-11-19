---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloudworld/entity/clash
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/clash.md
  type: wiki
supersedes: []
tags:
- 代理
- 出口路径
- 客户端
tier: canonical
title: Clash
updated_at: '2026-11-18T07:26:22Z'
---

> 客户端侧本地代理工具，因访问 memhub.work 时命中 GEOIP,CN,DIRECT 而使代理与直连共用同一出口，故被排除为握手重置的故障源。

# 定义

Clash 是运行在客户端侧的本地代理工具，负责按规则分流请求（直连 / 走代理节点）。在本次故障中它是被怀疑对象之一，但经验证被排除。

# 关键属性

- 规则体系中存在 `GEOIP,CN,DIRECT` 规则；访问 [[memhub.work]] 命中该规则，因此**代理与直连是同一条出口**。
- 经同一代理访问其他域名正常，说明代理本身工作正常。
- 经代理访问该域名 5 次同样失败，说明代理没有改变出口，也无法规避拦截。

# 关系

- 位于访问 [[memhub.work]] 的客户端路径上。
- 与 [[备案拦截（ICP 备案未完成阻断）]] 的关系：由于出口未变，代理绕不过按域名（SNI 层）实施的拦截。
- 给代理加 `DOMAIN-SUFFIX` 强制走境外节点可能避开某些出口的拦截，但多地区 reset 表明并非所有出口都通，不能作为稳定方案。
- 其排除结论由 [[SNI 分叉判据]] 与分层排除法共同支撑。

# 备注

本页内容偏薄，仅记录「出口策略与被排除」这一定位；若后续出现代理配置或分流规则类来源，应扩展规则集与节点选择相关属性。
