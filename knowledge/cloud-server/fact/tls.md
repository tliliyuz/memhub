---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/tls
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/tls-证书自动续期.md
  type: wiki
supersedes: []
tags:
- TLS
- 证书
- 自动化
tier: canonical
title: TLS 证书自动续期
updated_at: '2026-11-18T07:26:22Z'
---

> certbot --nginx + HTTP-01 + certbot.timer 的全自动证书机制，只依赖域名解析与 80 端口可达，与云厂商无关。

# TLS 证书自动续期

## 定义

使用 [[Let's Encrypt 与 certbot]] 的 `--nginx` 插件申请证书，通过 HTTP-01 校验证明域名所有权，再由 systemd 的 `certbot.timer` 周期性自动续期，无需人工介入。

## 机制

1. [[阿里云 DNS]] 将 [[memhub.work 域名]] 的 `@` / `www` 解析到 43.142.18.23。
2. `certbot --nginx` 借助 [[nginx]] 配置在 80 端口响应 `.well-known/acme-challenge/`。
3. 证书落地 `/etc/letsencrypt/live/memhub.work/`，由 nginx 在 443 加载。
4. `certbot.timer` 到期前自动续期并 reload。

时间线：签发 2026-11-11 03:58 UTC → 到期 2027-02-09 03:58 UTC。

## 意义

- **零成本、零绑定**：证书与云厂商无关，换主机只需改解析并保证 80 可达。
- **失败模式清晰**：唯一可能失败的原因是解析漂移或 80 端口被拦（[[腾讯云安全组]] / nginx 配置），因此 80 必须始终可达（只做 301，不可禁用）。
- 验证手段：`certbot renew --dry-run`（见 [[运维操作手册]]）。

## 相关实体

[[nginx]]、[[memhub.work 域名]]、[[阿里云 DNS]]、[[Let's Encrypt 与 certbot]]

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
