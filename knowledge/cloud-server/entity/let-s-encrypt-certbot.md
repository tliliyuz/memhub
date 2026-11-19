---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloud-server/entity/let-s-encrypt-certbot
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/let-s-encrypt-与-certbot.md
  type: wiki
supersedes: []
tags:
- TLS
- 证书
- 外部服务
tier: canonical
title: Let's Encrypt 与 certbot
updated_at: '2026-11-18T07:26:22Z'
---

> 为 memhub.work 签发免费 TLS 证书的外部 CA 与客户端工具，通过 certbot --nginx + HTTP-01 校验并由 timer 自动续期。

# Let's Encrypt 与 certbot

## 定义

外部证书签发机构 Let's Encrypt 及其官方客户端 certbot，用于为 [[memhub.work 域名]] 提供 HTTPS 证书。

## 关键属性

| 项目 | 值 |
|---|---|
| 插件 | `certbot --nginx` |
| 校验方式 | HTTP-01（要求 80 端口可达） |
| 签发时间 | 2026-11-11 03:58 UTC（11:58 UTC+8） |
| 到期时间 | 2027-02-09 03:58 UTC |
| 续期方式 | `certbot.timer` 自动，无需人工 |
| 证书路径 | `/etc/letsencrypt/live/memhub.work/` |
| 成本 | 免费，与阿里云无关 |

## 关系

- 证书被 [[nginx]] 在 443 上加载，构成 [[单入口反向代理架构]] 的 TLS 起点。
- 依赖 [[阿里云 DNS]] 的解析与 80 端口放行（[[腾讯云安全组]]）。
- 验证命令：`certbot renew --dry-run`（见 [[运维操作手册]]）。
- 完整机制见 [[TLS 证书自动续期]]。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
