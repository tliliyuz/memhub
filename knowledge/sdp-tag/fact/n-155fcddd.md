---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-155fcddd
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/本地联调启动基线.md
  type: wiki
supersedes: []
tags:
- 本地开发
- 启动参数
- 事故防范
tier: canonical
title: 本地联调启动基线
updated_at: '2026-11-18T07:26:22Z'
---

> 标准启动参数族——关 api-decrypt（否则登录 403）、关 captcha、关 snail-job（否则抢租约）、关 rabbit auto-startup（否则抢生产消息）、放行 198.18.0.0/15。

# 本地联调启动基线

## Definition

在本机启动 sdp-tag 后端时的**标准参数集**，用来避免本机实例干扰共享环境。

## Significance

这是**事故沉淀**：不加这些参数，本机实例会真的参与生产调度、抢生产消息，后果是数据损失而非「报个错」。

## 标准启动命令

```powershell
$env:PYTHONIOENCODING="utf-8"
java -jar sdptag-admin.jar `
  --spring.profiles.active=dev --server.port=18080 `
  --llm.chat.api-key=$env:LLM_CHAT_API_KEY `
  --captcha.enable=false --api-decrypt.enabled=false --snail-job.enabled=false `
  --spring.rabbitmq.listener.simple.auto-startup=false `
  --tag.image-fetch.allowed-networks=198.18.0.0/15 `
  --spring.datasource.dynamic.p6spy=false
```

## 参数逐条说明

| 参数 | 不加会怎样 |
| --- | --- |
| `--api-decrypt.enabled=false` | 登录 POST `/auth/login` 报 403「没有访问权限」 |
| `--captcha.enable=false` | 「验证码已失效」 |
| `--snail-job.enabled=false` | 本机连不上 `192.168.31.20:17888`；⚠️ **连共享环境会真参与调度，曾抢走 49 条任务租约** |
| `--spring.rabbitmq.listener.simple.auto-startup=false` | 本机实例会**抢生产 MQ 消息** |
| `--tag.image-fetch.allowed-networks=198.18.0.0/15` | 本机 Clash fake-IP 把图床解析到该段，被判内网拒绝 |

## 两个额外坑

- ⚠️ **`snail-job.port: 2${server.port}` 是字符串拼接**——换端口会拼出 `218123` 越界，需同时传 `--snail-job.port=`
- ⚠️ **`-D` 必须放在 `-jar` 之前**，每个 `-D` 单独加引号

## Related Entities

- [[snail-job]] / [[sdp-tag-snailjob]] — 不关则抢任务租约
- [[rabbitmq-vhost]] — 不关 `auto-startup` 则抢生产消息
- [[proxy-routing-policy]] — fake-IP 需放行 `198.18.0.0/15`
- [[sdp-tag-backend]] — 启动主体
- [[llm-gateway-applesay]] — `--llm.chat.api-key` 从环境变量取，不用 yml 默认

## Common Topics

- 部署模型 / 开发流程
- 事故防范

## Citations

- §3.3 本地起服务的标准参数（可直接抄）
