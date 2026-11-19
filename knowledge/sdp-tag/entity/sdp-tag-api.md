---
created_at: '2026-11-18T07:26:22Z'
entity_kind: service
id: sdp-tag/entity/sdp-tag-api
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/sdp-tag-api.md
  type: wiki
supersedes: []
tags:
- sdp-tag
- 服务
- 主链路
- k8s
- api服务
tier: canonical
title: sdp-tag-api
updated_at: '2026-11-18T07:26:22Z'
---

> 商品打标主服务，承载 precheck→场景→标签→回调完整链路，内含 Spring MQ 消费容器与租约重试机制；同时是集群 sdp-tag 命名空间的主 API 服务（镜像 sdp-tag-api，暴露 /prod-api），其部署清单与集群实际状态长期不一致。

# Definition

打标主服务（`app=sdp-tag-api`，namespace `sdp-tag`）。一条打标消息从 `precheck()` 进入，经场景阶段、标签阶段，最终触发回调；它同时是 MQ 消息的消费端与租约机制的持有者。

在集群侧，它也是 TKE 集群 `sdp-tag` 命名空间内的主 API 服务（后端 HTTP 入口），对外通过 `http://sdp-tag-web.applesay.cn/prod-api` 暴露。

# Key attributes

## 链路与阶段

- 四阶段：precheck → 场景（scene）→ 标签（label）→ 回调，见 [[打标四阶段链路]]。
- `precheck()` 失败**只写 `status=failed` 然后 `continue`，不记日志、不抛异常** → [[静默失败]]。
- `run-timeout` 只在批次之间检查，单次模型调用可以无限拖长（「卡死」与「慢」的区分点）。

## MQ 消费容器

| 属性 | 值 |
| --- | --- |
| `worker-threads` | 4 |
| `queue-capacity` | 200 |
| 拒绝策略 | `AbortPolicy`（日志 `异步打标任务队列已满`） |
| 保护逻辑 | 一条坏消息连续失败 3 次 → `MQ 消费容器已停止，修复原因后需人工恢复消费`，整条队列停摆 |

- 已知诱因：缺 `productName`、缺 `tenantId`（后者 NACK 不重回队列，瞬间烧掉几千条）。
- 消费链路是否通，用[[可观测性探针]]（故意发非法消息）判定，不要看 `consumers`。

## 租约与重试

租约 3 分钟 + 每次重领 `attempt_count+1`，超 4 次终态 failed 且**永不回调**——[[租约与重试上限]]。积压本身不可怕，租约过期计次才致命。

## 关键日志（INFO 级即可 grep）

| 日志 | 含义 |
| --- | --- |
| `回调成功，spu=…，第 1 次尝试` | 2xx 且 body.code 通过 |
| `回调业务失败（HTTP 200），url=…，响应=…` | 我们通了、对方拒绝（带响应体，最有用） |
| `回调密钥未配置，跳过回写：brand=…` | ⚠️ 文案误导，实际是「品牌不在允许列表」 |
| `未配置回调地址，仅记录结果：{payload}` | 地址为空，**带完整回写载荷**，抓请求体最省事 |
| `打标阶段失败，转死信，key=…` | 不会发起回调 |
| `打标完成但没有标签，key=…` | 会回调空结果 |
| `打标消息无法处理，转死信：brand 不能为空` | 功能探针的预期警告 |

`Received message` 是 DEBUG 级，默认看不到。

## 对外接口与指标

- `GET /tag/mq/rejected/list`、`POST /tag/mq/rejected/{id}/replay`（人工重放，见 [[tag_mq_rejected]]）
- `sdptag_mq_rejected_total{reason}`、`sdptag_mq_queue_depth{queue}`（连续 5 次超 5000 才 WARN）
- `TagMqQueueMonitor` 仅在 `auto-tagging.rabbit.enabled=true` 时生效

## 运行参数

- 环境变量命名陷阱：`tag.image-fetch.allowed-hosts` → `TAG_IMAGEFETCH_ALLOWEDHOSTS_0`（点换下划线、**连字符去掉**），写错**静默失效**，见 [[主图抓取放行模型]]。
- 本地绕开 `@ApiEncrypt`：`--api-decrypt.enabled=false --captcha.enable=false`。
- 自报身份：`config_hash` + 雪花 `worker` 位用于判断是否有旧配置进程在写同一库，见 [[雪花 ID 与进程识别]]。

## 部署与镜像

| 项 | 值 |
| --- | --- |
| 镜像名 | `sdp-tag-api`（位于 [[acr-registry]] 的 `applesaycn` 仓库） |
| 镜像 tag 格式 | `yyyyMMddHHmmss` |
| 部署清单 | `deploy/k8s/api.yaml` |
| 对外路径 | `/prod-api` |
| 运行命名空间 | `sdp-tag` |
| 关联 Secret | `acr-pull` / `sdp-tag-rabbit` / `sdp-tag-db` / `sdp-tag-callback` / `sdp-tag-api-runtime` |

# 已知问题

- 清单 tag（`20261030161500`）与集群实际跑的（`20261101184615`）**长期不一致**。
- 存在两份 `deploy/k8s/api.yaml`，其中 `D:\workplace\sdp-tag-k8s\deploy\k8s\api.yaml` 曾长期 untracked。
- 仓库清单里的 vhost / 并发是**测试口径**，随手 `kubectl apply` 会把生产流量切到 test vhost。
- `sdp-tag-api-runtime` Secret 只在 `deploy/README.md` 里存在，**清单没接** → 用仓库清单重建会回到 dev 行为。
- 清单 env **不覆盖阈值配置**（见 [[threshold-configuration]]）。

详见 [[deployment-manifest-drift]]。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[tag_task]] | 任务状态真相源（`task_status`/`attempt_count`/`lease_expire_time`） |
| [[tag_callback_delivery]] | 回调投递留痕，由其 `status` 判定投递是否完好 |
| [[tag_mq_rejected]] | 拒收留痕与人工重放 |
| [[aliyun-serverless-amqp]] | 上游消息中间件（5672，无 15672） |
| [[ingress-nginx]] / [[sdp-tag-web]] | 端到端超时的两层天花板，见 [[分层超时]]；其中 `sdp-tag-web` 同时是本服务的上游调用方 |
| [[ImageAddressPolicy]] | precheck 主图放行判定 |
| [[llm-gateway]] | 模型调用入口 |
| [[snailjob]] | 调度客户端，端点配置分离会导致隐藏重试 |
| [[tke-cluster-cls-62409zrl]] | 部署于该集群 |
| [[acr-registry]] | 镜像仓库（`applesaycn`） |
| [[image-release-pipeline]] | 镜像发布遵循该流水线 |
| [[pod-relay-image-push]] / [[acr-relay]] | 紧急发布时经 acr-relay 中转推送 |
| [[deployment-manifest-drift]] | 清单与实跑漂移问题记录 |
| [[k8s-secret-injection]] | 配置注入方式 |
| [[threshold-configuration]] | 清单 env 不覆盖阈值配置 |

# Citations

- 04 排障信号手册 §1.1、§1.5、§2.1、§3.1–§3.4、§4.8、§4.11
- 05 配置与凭据地图 §2 集群与部署表、§2.3 镜像 tag 规则与致命组合、§2.4 部署清单漂移（真实事故）
