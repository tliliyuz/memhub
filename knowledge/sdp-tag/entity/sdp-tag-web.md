---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: sdp-tag/entity/sdp-tag-web
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/sdp-tag-web.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 服务
- 前端
- 网关
- ingress
tier: canonical
title: sdp-tag-web
updated_at: '2026-11-18T07:26:22Z'
---

> sdp-tag 前端服务与访问入口（http://sdp-tag-web.applesay.cn，仅 http），容器内 nginx 负责反向代理与超时控制；proxy_pass 启动时解析可致 CrashLoop，并构成与 ingress 并列的第二层 300s 超时天花板。

# sdp-tag-web

## Definition

sdp-tag 的前端服务与访问入口：前端静态资源 + 容器内 nginx 反向代理层，把浏览器请求转发到 [[sdp-tag-api]]；后端 API 经 `/prod-api` 反向代理至 [[sdp-tag-api]]。它既是超时链路的第二层天花板，也是 web 容器启动顺序问题的现场。

## Key attributes

| 项 | 值 |
| --- | --- |
| 访问入口 | `http://sdp-tag-web.applesay.cn` |
| 镜像名 | `sdp-tag-web`（[[acr-registry]]） |
| 协议 | **仅 http**（无 TLS） |
| 同域子路径 | `/snail-job`（[[snail-job]] 控制台，iframe 嵌入） |

- **`proxy_pass` 在启动时解析**：api Service 不存在时报 `nginx: [emerg] host not found in upstream "sdp-tag-api"` → web CrashLoop，看起来像镜像坏了。**先建 api Service，再建 web Deployment**。
- **第二层超时**：容器内 nginx `proxy_read_timeout` 默认 300s（已改 600），配置在 `deploy/web/nginx.conf`，**改了要重建 web 镜像**。见 [[分层超时]]。
- **判别信号**：端到端 504 时，web 的 nginx 记 `499`（客户端断开），且应用日志里根本没有这次请求 → 请求在 [[ingress-nginx]] 层就被掐断。
- **发布校验**：前端入口 `/assets/index-XXXX.js` 的 hash 需与本地 `dist` 一致，见 [[发布生效三步校验]]。

## Relationships

| 关联 | 关系 |
| --- | --- |
| [[sdp-tag-api]] | 上游后端；Service 必须先存在，API 经 `/prod-api` 反向代理 |
| [[ingress-nginx]] | 上层 60s 天花板，短的那个赢 |
| [[分层超时]] | 超时机制的归属概念页 |
| [[tke-cluster-cls-62409zrl]] | 部署集群，命名空间 `sdp-tag` |
| [[image-release-pipeline]] | 镜像发布流程 |
| [[snail-job]] | 同域挂载，nginx 必须配 `location /snail-job` |

## 已知问题

- `ingress.yaml` 的 `tls` 段**仍是注释** → 站点只有 http，凭据与 API Key 全程明文传输（加重 [[api-key-authorization]] 的风险）。
- SnailJob 控制台是 iframe，nginx 缺 `location /snail-job` 就会白屏。

## Citations

- 04 排障信号手册 §4.9（判别方法）、§4.10
- 05 配置与凭据地图 §2 集群与部署表（访问入口行）
