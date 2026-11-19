---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: sdp-tag/entity/sdp-tag-backend
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/sdp-tag-backend.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- spring-boot
- 后端应用
tier: canonical
title: sdp-tag-backend
updated_at: '2026-11-18T07:26:22Z'
---

> sdp-tag 的 Spring Boot 后端应用本体，启动模块 sdptag-admin，配置文件位于 src/main/resources，是本次凭据泄露问题的核心载体。

# sdp-tag-backend

## Definition

sdp-tag 的 Spring Boot 后端应用本体，启动模块为 `sdptag-admin`。它是整个系统配置问题的**核心载体**：配置文件、明文凭据、环境变量绑定、回调逻辑、租户上下文都落在这个应用里。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 启动模块 | `sdptag-admin`（产物 `sdptag-admin.jar`） |
| 配置文件（仓库内） | `sdp-tag-backend/sdptag-admin/src/main/resources/application{,-dev,-prod}.yml` |
| 配置文件（运行目录覆盖） | `<cwd>/config/application-private.yml`（Git 忽略） |
| 配置文件（容器内） | `/sdptag/server/config/application-private.yml`（Secret 只读挂载） |
| 激活 profile | `dev` / `prod` |
| 本地默认端口 | `18080`（标准启动参数里） |

## 配置相关职责

- 承载 [[config-layering]] 的五层配置优先级链条
- 通过 [[env-var-relaxed-binding]] 接收 K8s 注入的环境变量
- 通过 [[k8s-secret-injection]] 读取挂载的 `application-private.yml` 与 Secret 环境变量
- 通过 [[callback-and-brand-allowlist]] 向外回调业务方（[[partner-brand-tenant]]）
- 通过 [[tenant-context]] 维护 `dynamicTenant` 会话上下文
- 通过 [[threshold-configuration]] 判定打标/判分阈值
- 通过 [[llm-gateway-applesay]]、[[system-one-typesafe]]、[[ark-volces]] 三条路径调用模型

## Relationships

- **部署载体**：[[tke-cluster-cls-62409zrl]]（命名空间 `sdp-tag`）
- **镜像**：与 [[sdp-tag-api]]、[[sdp-tag-web]]、[[sdp-tag-snailjob]] 同属一个 ACR 仓库 [[acr-registry]]
- **数据依赖**：[[aliyun-rds-instances]]、[[redis-tencent-clb]]、[[rabbitmq-vhost]]
- **凭据风险**：`application-dev.yml:58` / `application-prod.yml:62` 明文 RDS root 口令 → [[credential-leak-and-rotation]]
- **代码仓库**：[[gogs-sdp-tag]]

## 已知问题

- RDS root 与 ACR 口令同值，明文进 git 历史（P0-1）
- Redis 口令明文在 `application-dev.yml:112`
- LLM `api-key` 默认值写死在 `application.yml`
- `config/application-private.yml` 优先级低于 `application.yml`，写进去永不生效
- `snail-job.port: 2${server.port}` 是字符串拼接，换端口易越界

## Citations

- §1 配置文件分层与位置
- §3.3 本地起服务标准参数
- §9 绝不能进仓库的清单
