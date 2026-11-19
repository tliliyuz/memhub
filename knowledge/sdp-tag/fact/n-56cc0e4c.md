---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-56cc0e4c
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/sources/05-配置与凭据地图.md
  type: wiki
supersedes: []
tags:
- 运维
- 配置管理
- 凭据安全
- 部署
- sdp-tag
tier: canonical
title: 05 · 配置与凭据地图
updated_at: '2026-11-18T07:26:22Z'
---

> sdp-tag 系统的配置分层、部署发布、环境变量绑定、数据库/Redis/LLM/代理/评测/代码仓库连接与凭据现状的权威运维底稿，记录三类系统性风险。

# 05 · 配置与凭据地图

> **本文档不进仓库。** 记录「哪个配置在哪、怎么生效、有什么坑」，以及**哪些凭据已经泄露需要轮换**。凭据一律只写前 8 位 + `…`。

## 文档摘要

本文是 sdp-tag 系统的**配置与凭据情报库**，覆盖范围：

| 章节 | 内容 |
| --- | --- |
| §0 | 必须立即处理的 P0 事项（凭据泄露） |
| §1 | Spring Boot 配置文件分层与优先级 |
| §2 | 集群、部署、镜像发布、清单漂移 |
| §3 | 环境变量命名绑定规则与各环境成对取值 |
| §4 | 数据库、隔离测试库、Redis、SQL 执行 |
| §5 | LLM 网关与 key、判分三种终点 |
| §6 | 代理与网络策略 |
| §7 | 评测工具 `tools/lab-accuracy` |
| §8 | Git 仓库与凭据 |
| §9 | 绝不能进仓库的清单 |
| §10 | 凭据风险汇总（按严重度分级） |

## 三类系统性风险

### 1. 凭据明文落库 / 落 git 历史且已实质泄露

- **P0-1**：MySQL root 口令与阿里云 ACR 口令是**同一个值**（`sx@12345…`），取一处即攻破镜像仓库 + dev 库 + 生产库三处 → [[credential-leak-and-rotation]]
- **P0-2**：图谱导出 API Key `sk_5dIyx…` 明文提交进 git，有效期 365 天，接口为 http 且无 IP 白名单、无限流 → [[api-key-authorization]]
- **P0-3**：对方租户 `cfg_api_key` 被 root 直读、回调 api-key 与品牌 token 明文外流 → [[partner-brand-tenant]]
- **P0-4**：7 把 LLM key 明文出现在会话与 yml 默认值里 → [[llm-gateway-applesay]]
- 另有 cluster-admin 级 kubeconfig 落在 `Downloads` → [[ops-subaccount-cluster-admin]]，评测平台 `admin/admin123` 弱口令 → [[lab-admin-account]]

### 2. 一组反直觉的配置生效规则

- [[config-layering]]：`config/application-private.yml` 优先级**低于** `application.yml`，写进去永不生效；`optional:` 使其缺失时静默跳过
- [[env-var-relaxed-binding]]：点换下划线、**去掉连字符**、大写——写错不报错、静默失效
- [[proxy-routing-policy]]：两个 LLM 终点代理策略**相反**（网关必须直连、Typesafe 必须走代理）
- [[threshold-configuration]]：三套阈值并存（pipeline / lab / DB 回落 / gate-threshold），改 yaml env 不生效

### 3. 真实事故沉淀的操作禁令

- [[deployment-manifest-drift]]：清单 tag 与集群实跑不一致、untracked 清单、`kubectl apply` 覆盖 `set env`
- [[image-release-pipeline]]：可覆盖 tag + `IfNotPresent` = 重推不重拉
- [[local-dev-runtime-baseline]]：本机不关 SnailJob 会真参与调度（曾抢走 49 条任务租约）、不关 rabbit `auto-startup` 会抢生产消息
- [[db-schema-change-management]]：无 Flyway/Liquibase，打包部署重启都不执行 SQL

## 出处批次

| 批次 | 来源 |
| --- | --- |
| `[C]` | Codex 会话导出 |
| `[D]` | DSH 会话导出（11 月权威） |
| `[Z]` | zcode 记忆（部署/网络细节权威） |

## 待补链接

本文多处引用尚未入库的文档，后续来源入库后应回填：

- `[01-术语实义](01-术语实义.md)` §13：`llm.judge.*` 与 `llm.chat.*` 两条路径的行为差异
- `docs/Spec/2026-10-28-图谱接口示例.md`（图谱导出接口示例，含已泄露的 Key）
- `deploy/README.md`（Secret 清单权威出处）
- `sdp-tag-backend/script/sql/README.md`（SQL 脚本命名与台账）
- `tools/lab-accuracy/README.md`（评测工具用法）

## Citations

- §0 P0 事项 → [[credential-leak-and-rotation]]
- §1 配置分层 → [[config-layering]]
- §2 集群/部署/镜像 → [[tke-cluster-cls-62409zrl]]、[[deployment-manifest-drift]]、[[image-release-pipeline]]、[[pod-relay-image-push]]
- §3 环境变量 → [[env-var-relaxed-binding]]、[[environment-isolation]]、[[callback-and-brand-allowlist]]、[[local-dev-runtime-baseline]]
- §4 数据库 → [[aliyun-rds-instances]]、[[redis-tencent-clb]]、[[db-schema-change-management]]、[[isolated-test-db-guard]]、[[tenant-context]]
- §5 LLM → [[llm-gateway-applesay]]、[[system-one-typesafe]]、[[ark-volces]]、[[threshold-configuration]]
- §6 代理 → [[proxy-routing-policy]]
- §7 评测 → [[lab-evaluation-framework]]、[[lab-accuracy-tool]]、[[lab-admin-account]]
- §8 Git → [[gogs-sdp-tag]]
- §10 风险汇总 → [[credential-leak-and-rotation]]
