---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: cloud-server/entity/nginx
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/nginx.md
  type: wiki
supersedes: []
tags:
- 反向代理
- 入口
- 服务
tier: canonical
title: nginx
updated_at: '2026-11-18T07:26:22Z'
---

> memhub 记忆栈唯一的公网入口反向代理，负责 TLS 终止、80→443 跳转、限流与安全响应头，并将面板流量转发到回环端口。

# nginx

## 定义

`nginx.service`，监听 80 / 443，是 [[memhub.work 域名]] 的唯一公网收口，实现 [[单入口反向代理架构]]。所有内部服务（除 SSH）都不直接对公网暴露。

## 关键属性

- 监听：80（0.0.0.0，301 → 443）、443（0.0.0.0，TLS 终止）。
- 反代目标：`127.0.0.1:8125`（[[tdai-memory-hub]] 面板）。
- 限流：`/api/v1/auth/` 6 次/分（burst 4）；其余 30 次/秒（burst 60）。
- 安全头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: no-referrer`、隐藏 nginx 版本号。
- 配置文件：`/etc/nginx/sites-available/memhub`、`/etc/nginx/proxy_params_memhub`。
- TLS 证书来自 [[Let's Encrypt 与 certbot]]（`/etc/letsencrypt/live/memhub.work/`）。

## 关系

- 上游：互联网用户（[[浏览器用户]]）。
- 下游：[[tdai-memory-hub]] → [[tdai-memory-core]]。
- 实例化 [[最小暴露面绑定原则]] 的"唯一例外"（22/80/443）。
- 属于 [[主机安全防护分层]] 的应用层（限流 + 安全头）。
- 运维：`nginx -t && systemctl reload nginx`（[[运维操作手册]]）。
- 未来新增公网能力（如暴露 [[tdai-proxy]]）必须经过本层 + 鉴权。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
