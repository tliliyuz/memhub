---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/minimal-exposure-binding-77bf77
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/other/minimal-exposure-binding.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: minimal-exposure-binding
updated_at: '2026-11-18T07:26:22Z'
---

# 最小暴露面绑定原则

## 定义

主机上任何服务的监听地址都必须**显式限定在最小可达范围**：

1. 只有 SSH(22)、HTTP(80)、HTTPS(443) 绑 `0.0.0.0`；
2. 其余所有服务仅绑 `127.0.0.1`（本机/反代可达）；
3. 需要跨容器访问的宿主机进程绑 `172.17.0.1`（docker0），使容器可达而公网不可达；
4. 容器端口发布一律带 `127.0.0.1:` 前缀。

## 意义

- 暴露面不再依赖防火墙规则的正确性：即使 [[腾讯云安全组]] 或 ufw 配置失误，未绑公网地址的端口也无法从外部直达。
- 与 [[单入口反向代理架构]] 互为表里：绑定层做"不可达"，代理层做"受控可达"。
- 是新增服务时的默认动作——先问"它需要被谁访问"，再决定绑定地址。

## 实例

| 服务 | 绑定 | 依据 |
|---|---|---|
| [[nginx]] | 0.0.0.0:80/443 | 唯一公网入口 |
| SSH | 0.0.0.0:22 | 运维通道 |
| [[tdai-memory-hub]] panel | 127.0.0.1:8125 | 经 nginx 反代 |
| [[tdai-memory-hub]] knowledge | 127.0.0.1:8424 | 仅本机 |
| [[tdai-memory-core]] | 127.0.0.1:8420 | 仅本机 |
| [[tdai-proxy]] | 127.0.0.1:8096 | 客户端经 SSH 隧道 |
| [[magpie gateway]] | 172.17.0.1:3425 | 容器可达、公网不可达 |
| magpie web UI | 127.0.0.1:3430 | 仅本机 |
| [[systemd-resolved]] | 127.0.0.53/54:53 | 仅本机 |

## 相关实体

[[nginx]]、[[tdai-memory-hub]]、[[tdai-memory-core]]、[[tdai-proxy]]、[[magpie gateway]]、[[Docker]]、[[腾讯云安全组]]

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
