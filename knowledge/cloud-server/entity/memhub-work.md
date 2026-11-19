---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/memhub-work
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/memhub-work-域名.md
  type: wiki
supersedes: []
tags:
- 域名
- DNS
- 入口
tier: canonical
title: memhub.work 域名
updated_at: '2026-11-18T07:26:22Z'
---

> 主域名 memhub.work 及 www 子域，A 记录指向 43.142.18.23，是 memhub 记忆栈唯一的公网业务入口标识。

# memhub.work 域名

## 定义

业务主域名 `memhub.work`，同时包含 `www.memhub.work` 子域。两条 A 记录均指向 [[腾讯云 CVM VM-0-10-ubuntu]] 的公网 IP 43.142.18.23，因此对外表现为单一入口。

## 关键属性

- 解析服务商：[[阿里云 DNS]]（dns27/dns28.hichina.com），与腾讯云主机解耦。
- A 记录：`@` 与 `www` → 43.142.18.23。
- 仅用于 HTTPS 业务入口；HTTP(80) 一律 301 跳转到 443，由 [[nginx]] 处理。
- 证书主体：[[Let's Encrypt 与 certbot]] 签发，路径 `/etc/letsencrypt/live/memhub.work/`。

## 关系

- [[nginx]] 的站点配置 `/etc/nginx/sites-available/memhub` 以该域名定义 server_name，承载 [[单入口反向代理架构]]。
- 证书生命周期由 [[TLS 证书自动续期]] 管理，只依赖"解析到此机 + 80 端口可达"。
- 待办：如未来要暴露 [[tdai-proxy]] 的 8096 端口，可为其申请独立子域名并走反代 + 鉴权。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
