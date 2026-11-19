---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloudworld/entity/nginx
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/nginx.md
  type: wiki
supersedes: []
tags:
- 反向代理
- TLS终结
- 服务端
tier: canonical
title: Nginx
updated_at: '2026-11-18T07:26:22Z'
---

> 服务端反向代理与 TLS 终结者，经不带 SNI 的 IP 直连返回 200 且证书 CN 正确，从而被排除为本次握手重置的故障源。

# 定义

服务端 nginx 承担反向代理与 TLS 终结职责：对明文 :80 请求返回 301 跳转，对 HTTPS 请求提供证书并转发到后端服务。

# 关键属性

- TLS 终结者，持有 `CN=memhub.work` 的证书。
- 明文 :80 返回 301，响应被判定为「真实 nginx 响应」，证明网络通路本身正常。
- 不做 SNI 拒绝：服务端自身与另一地区服务器直连该 IP、使用各种 SNI 均握手成功。

# 关系

- 服务于域名 [[memhub.work]]。
- 在 [[SNI 分叉判据]] 中充当**服务端对照**：IP 直连 + `Host:` 头（不带 SNI）返回 200 且证书正确，说明证书与 nginx 配置均无问题。
- 其正常响应是排除「服务端 / 证书错」假设的直接依据，最终根因归于 [[备案拦截（ICP 备案未完成阻断）]]。

# 备注

本页目前仅由归因类来源支撑，内容聚焦「被排除」这一结论。若后续出现服务端配置、证书管理或 DNS-01 签发类来源，应在此扩展部署拓扑与证书属性段。
