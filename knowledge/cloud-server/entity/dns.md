---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloud-server/entity/dns
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/阿里云-dns.md
  type: wiki
supersedes: []
tags:
- DNS
- 外部服务
- 阿里云
tier: canonical
title: 阿里云 DNS
updated_at: '2026-11-18T07:26:22Z'
---

> memhub.work 的外部权威 DNS 服务（dns27/dns28.hichina.com），与腾讯云主机解耦。

# 阿里云 DNS

## 定义

为 [[memhub.work 域名]] 提供权威解析的外部 DNS 服务，NS 为 `dns27.hichina.com` / `dns28.hichina.com`。

## 关键属性

- 记录：`@` 与 `www` 两条 A 记录 → 43.142.18.23（[[腾讯云 CVM VM-0-10-ubuntu]]）。
- 与云主机厂商不一致：域名在阿里云、主机在腾讯云，两者仅通过 A 记录耦合。

## 关系

- 是 [[TLS 证书自动续期]] 的前置条件之一：HTTP-01 校验要求域名解析指向本机。
- 解析变更不影响证书本身（Let's Encrypt 证书与云厂商无关）。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
