---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/memhub-work
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/memhub-work.md
  type: wiki
supersedes: []
tags:
- 域名
- TLS
- ICP备案
tier: canonical
title: memhub.work
updated_at: '2026-11-18T07:26:22Z'
---

> 承载 HTTPS 服务的目标域名，本次 TLS 握手重置故障与所有应对方案均以该域名为锚点；因 ICP 备案未完成而被边缘网络按域名拦截。

# 定义

`memhub.work` 是承载 HTTPS 服务的域名（属「域名 / 资源标识」类实体），是本次故障诊断与所有方案取舍的锚点对象：拦截发生在该域名的 SNI 上，过渡方案绕开它，长期方案要么给它补备案、要么替换它。

# 关键属性

| 属性 | 值 / 状态 |
| --- | --- |
| 服务承载端口 | HTTPS 443（服务器侧），明文 80 返回 301 跳转 |
| 证书 | 证书 `CN=memhub.work`，IP 直连不带 SNI 时验证正常 |
| 备案状态 | **ICP 备案未完成** —— 这是被拦截的前提条件 |
| 公网可达性 | 部分网络带 SNI 访问全部被重置；部分地区 200；不同出口表现不一致 |
| 过渡访问入口 | `127.0.0.1:8443`（经 SSH 隧道映射到服务器 443） |

# 关系

- 由 [[Nginx]] 终结 TLS 并提供 301 跳转与证书。
- 其备案状态决定是否触发 [[备案拦截（ICP 备案未完成阻断）]]。
- 访问路径上可能经过客户端代理 [[Clash]]，但代理不改变出口，因此绕不过拦截。
- 是 [[SNI 分叉判据]] 的应用对象：带 SNI 死、不带 SNI 活。
- 过渡期通过 [[SSH 隧道过渡方案]] 的 loopback 入口访问。
- 长期出路：完成 ICP 备案，或换用已备案域名。

# 已知边界

「换证书无效」的边界条件是：拦截发生在 SNI 层，与证书链无关，因此 DNS-01 等方式重签证书不改变结果。
