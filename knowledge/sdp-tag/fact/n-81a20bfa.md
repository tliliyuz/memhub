---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-81a20bfa
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/代理策略-终点相反.md
  type: wiki
supersedes: []
tags:
- 网络
- 代理
- 排障
tier: canonical
title: 代理策略（终点相反）
updated_at: '2026-11-18T07:26:22Z'
---

> LLM 网关必须直连、Typesafe 必须走代理，是最容易搞错的一条；JVM 不读 HTTP_PROXY 需 -Dhttps.proxyHost；Clash fake-IP 198.18.0.0/15 被判内网。

# 代理策略（终点相反）

## Definition

sdp-tag 运行环境中对各类外部终点「走代理还是直连」的差异化规则。

## Significance

> ⚠️ **两个 LLM 终点代理策略相反——这是最容易搞错的一条。**

搞错的症状是 timeout / 451，但**原因不明显**，容易误判成对方服务故障。

## 终点对照表

| 终点 | 策略 | 症状 |
| --- | --- | --- |
| [[llm-gateway-applesay]]（`applesay-api-hup.applesay.cn`） | ⚠️ **必须直连** | 走代理会 timeout |
| [[system-one-typesafe]]（`api.typesafe.ai`） | ⚠️ **必须走代理** | 直连返回 **451** |
| [[ark-volces]]（`ark.cn-beijing.volces.com`） | 走代理 + 必需头 | 缺头 404 空 body |
| [[redis-tencent-clb]] | **必须绕开**（跨云） | 需进 `nonProxyHosts` |

## 基础配置

| 项 | 值 |
| --- | --- |
| HTTP/SOCKS 代理 | `127.0.0.1:7897`（Clash） |
| nonProxyHosts | `localhost\|127.0.0.1\|*.local\|*.myqcloud.com\|*.sh-tencentclb.cloud\|*.aliyuncs.com` |

## 四类坑

1. **JVM 不读 `HTTP_PROXY` 环境变量**（`proxySelector -> [DIRECT]`）→ 必须用 `-Dhttps.proxyHost` 系统属性，**在 `-jar` 之前**，每个 `-D` 单独引号。
2. **Clash fake-IP**：把公网域名解析到 `198.18.0.0/15`，被主图安全策略判为内网 → 放行该段（仅本机，见 [[local-dev-runtime-baseline]]）。
3. **记忆/skill bridge**：注入提示词里的 `172.18.0.4:8096` 是**容器内地址，桌面端不可达**；实测生效的是 `127.0.0.1:8096`。`NO_PROXY` 不含目标网段时走代理必然 502 → 先 `curl --noproxy '*'` 验证。
4. **Docker 的两个代理配置不同** `[Z]`：
   - **daemon 代理**写在 `%APPDATA%\Docker\settings-store.json`（键是 `ProxyHTTPMode` / `OverrideProxyHTTP` / `OverrideProxyHTTPS` — **HTTP 全大写**）
   - **buildkit 不继承 daemon 代理** → `docker build` 拉 FROM 仍会直连超时。真正解决靠 `%USERPROFILE%\.docker\daemon.json` 的 `registry-mirrors`

## Related Entities

- [[llm-gateway-applesay]]、[[system-one-typesafe]]、[[ark-volces]]
- [[redis-tencent-clb]] — 跨云 → nonProxyHosts
- [[pod-relay-image-push]] — 直推失败的另一侧面
- [[local-dev-runtime-baseline]] — fake-IP 需放行

## Common Topics

- 部署模型
- 网络与外部系统集成

## Citations

- §5 代理相反的终点
- §6 代理与网络
