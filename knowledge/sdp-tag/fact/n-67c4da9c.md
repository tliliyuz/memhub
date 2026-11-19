---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-67c4da9c
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/运维与发版规范.md
  type: wiki
supersedes: []
tags:
- 运维
- 发版
- 部署
tier: canonical
title: 运维与发版规范
updated_at: '2026-11-18T07:26:22Z'
---

> 「等队列跑空再发版」应反转为立刻停；镜像 tag 可覆盖 + IfNotPresent 会推旧镜像；禁止本机实例连共享 dev。

# 定义

运维与发版规范是围绕发版时机、镜像制品、实例接入、运行时打包等环节的操作纪律，多数条目来自真实事故。

# Schema：规范与反例

| 规范 | 反例 / 机制 | 出处 |
| --- | --- | --- |
| **发版要立刻停，不要等队列跑空** | 旧代码写的 `tagged_input_hash` 为 NULL → 缓存永命不中 → 次日同商品被原样重打（约 18.7 万 token/件） | D1 |
| **镜像 tag 必须不可变（唯一 tag / 摘要）** | 时间戳 tag 可覆盖 + `imagePullPolicy: IfNotPresent` = 同名 tag 重推**不会重新拉取**；推的 `20261029095256` 摘要 `0f0b3156…` 正是集群在跑的旧镜像 | D10 |
| **不信部署清单** | `deploy/k8s/api.yaml` 写 `20261030161500`，集群实际跑 `20261101184615` | D10 / G12 |
| **本机/临时实例禁止连共享 dev** | 实例启动即加入 MQ 消费与 SnailJob 调度组，~4 分钟窗口抢走 **49 条** `task_status='1'` 且租约未过期 | D9 |
| **拉 openapi 的实例必须 `spring.rabbitmq.listener.simple.auto-startup=false`** | 同上 | D9 |
| **测试实例加 `-Dsnail-job.enabled=false`** | 同上 | D9 |
| **不要在运行时重新打包 jar** | 本地 `java -jar` 持有 Windows 文件锁 → `repackage` 失败（`Unable to rename ... .jar.original`）→ 留下 4MB thin jar → HTTP 全挂；**不要 kill 那个进程**，在一次性 worktree 里构建 | D11 |
| **直接改 DB 配置不算改配置** | `tag_field_config` 无 `ON UPDATE CURRENT_TIMESTAMP`，裸 SQL 不填 `update_time` → 看起来像「租户本来就配了 0」，导致错误归因差点改 `TenantHelper`；`sys_config` 走 Redis hash 缓存，改 MySQL 必须 `HDEL` 对应字段；`PUT /tag/fieldConfig` 只传两个字段会**清空**其它字段（非 PATCH 语义） | D6 / D7 |
| **长任务用 detached 进程，不用 `run_in_background`** | harness 在 turn 结束时回收子进程 → `EXIT=127`、`BLOB_UPLOAD_INVALID`，误判成网络问题一小时；改 `Start-Process -PassThru` 后 29 KB/s + 15 次重置 → 61~66 KB/s、0 重置 | D16 |

# 另见

- 缺口 G7（无 graceful shutdown / `preStop`）、G12（清单漂移）见 [[已知未修缺口清单]]。
- 环境级坑（ACR 推送、配置绑定、代理、Git 共享工作区）见 [[开发环境与工具链陷阱]]。
- 消息侧可靠性见 [[消息可靠性与死信（DLX）]]。

# 相关实体

- [[消息队列 / 阿里云 Serverless AMQP]]、[[实验台（lab）]]、[[打标引擎（TagEngine）]]

# Citations

- D1、D6、D7、D9、D10、D11、D16、G7、G12；出处见 [[03-失败与被推翻]]。
