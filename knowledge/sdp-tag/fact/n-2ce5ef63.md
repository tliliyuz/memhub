---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-2ce5ef63
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/sources/04-排障信号手册.md
  type: wiki
supersedes: []
tags:
- 排障
- 运维
- 评测
- sdp-tag
- 信号
tier: canonical
title: 04 排障信号手册
updated_at: '2026-11-18T07:26:22Z'
---

> sdp-tag 商品打标系统的排障信号手册摘要：按症状→首查项→判据组织回调、MQ、打标、环境发布、评测五个域的第一现场与判据。

# 文档概览

一份面向 sdp-tag（商品打标系统）的**排障信号手册**：以「症状 → 首查项 → 判据」的两级速查结构（0 章通用症状表 + 1~5 章编号小节），给出回调链路、MQ 链路、打标链路、环境与发布、评测侧五个域的**日志 / 库表 / 指标第一现场**与判据。

它是运维与评测的经验知识沉淀，而非架构设计文档：核心价值在于标注大量「看起来是 A 其实是 B」的**静默失败、假成功与脏指标陷阱**。

# 总原则

> **先证明现象是缺陷，再找根因。** 记录里 4 次误判都发生在「急于给出解释」的时候。

详见 [[排障范式]]。

# 结构

| 章 | 主题 | 主要落点 |
| --- | --- | --- |
| 0 | 症状 → 首查项速查表 | 入口分流 |
| 1 | 回调链路 | [[tag_callback_delivery]]，`delivered` vs `callback_done` |
| 2 | MQ 链路 | [[aliyun-serverless-amqp]]、[[可观测性探针]] |
| 3 | 打标链路 | [[打标四阶段链路]]、[[租约与重试上限]] |
| 4 | 环境与发布 | [[配置生效与三源优先级]]、[[发布生效三步校验]]、[[分层超时]] |
| 5 | 评测侧 | [[评测口径一致性]]、[[分数带与准确率映射]] |
| 6 | 库表 / 日志固有陷阱 | 列名陷阱、日志轮转 |
| 7 | 可复用排查范式 | [[排障范式]] |

# 症状速查（节选）

| 症状 | 先看什么 | 判据 |
| --- | --- | --- |
| 打标完成但 0 标签 | 这条消息**发出过几次模型请求** | **零请求** = 卡在 precheck，不是模型问题 |
| 标签数突然少三成 | `gateThreshold` vs `dimensionThresholds` | 闸门高于正式阈值时那部分标签**永远不产出且不报错**（[[闸门阈值]]） |
| 回调 200 但对方没数据 | 直接查对方落库表，**按时间窗查不要按 spu 查** | 按 spu 查会因 id 拼错漏看 |
| 回调「成功」但业务没生效 | 判定是否只看了 2xx | 假成功（[[假成功与严格成功判据]]） |
| 打标成功但没回调 | `tag_callback_delivery` 有没有行 | 缺 event，不是缺权限 |
| 回调没发出（快速排除） | 比 `delivered` 与 `callback_done` 计数 | **相等即投递链路完好** |
| 任务大面积 failed | `attempt_count` 是否到 4 | 「任务执行次数已达上限，过期租约不再重试」 |
| 任务排队不动 | 日志 `异步打标任务队列已满` | 4 线程 / 200 队列 / AbortPolicy |
| 消费容器自己停了 | 日志 `MQ 消费容器已停止，修复原因后需人工恢复消费` | 一条坏消息连败 3 次停整条队列 |
| 消息没被消费 | AMQP 被动声明查 `messages` / `consumers` | ⚠️ `consumers` 可能不可信 → [[可观测性探针]] |
| 配置改了没生效 | `update_time` 有没有动 / 是否 `secretKeyRef` / Redis 缓存 | [[配置生效与三源优先级]] |
| 发布是否真生效 | **md5 + imageID + 前端入口 hash** 三步 | [[发布生效三步校验]] |
| 模型 503 | 同一把 key 单打网关 + 查 `/v1/models` | [[llm-gateway]]，别急着换模型 |
| 主图抓不到 | 域名是否被解析到 `198.18.0.0/15` 或 `169.254.x.x` | [[主图抓取放行模型]] |
| 端到端 504 | 是 ingress 的 60s 还是 web nginx 的 300s | [[分层超时]] |
| web 容器起不来 | `nginx: [emerg] host not found in upstream` | 先建 api Service（[[sdp-tag-web]]） |
| lab 跑出来不稳定 | 是 `chat` 源还是 `systemone` 源 | [[chat 源 vs systemone 源（judge 对比）]] |
| 任务莫名失败、有人同时在写 | 雪花 ID 的 worker 位 + `config_hash` | [[雪花 ID 与进程识别]] |

# 库表 / 日志固有陷阱

**列名易错**（会让人白查半天）：

| 想查 | 实际列名 |
| --- | --- |
| 事件状态 | `tag_event.status`（**不是** `event_status`） |
| 字段编码 | `tag_field_config.field_code`（**不是** `field_key`） |
| 图谱维度删除标记 | `graph_dimension` **没有** `del_flag` |
| 调度任务时间 | `sj_job_task.create_dt` / `update_dt`（**不是** `create_time`） |
| 标签定义 | `graph_label.remark`（**没有** `definition`，**也不是** `label_remark`） |
| Prompt 版本主键 | `sys_prompt_version.id`（**不是** `version_id`） |

- **日志会被轮转截断**：PowerShell 管道读日志被 10MiB 轮转截断（`--since=60m` 实际只有 258 秒窗口）→ 不能把计数当小时值。
- **日志丢了查库**：`tag_task_evidence.evidence_gzip` 有每阶段 `elapsedMs` / token，比日志可靠。
- **Git Bash 中文结果集乱码**：重定向到临时文件再用工具读，用 `\G` 与窄列名。
- **终端中文乱码**：`PYTHONIOENCODING=utf-8` + `sys.stdout.reconfigure(encoding='utf-8')`。
- **大导出文件不要直接 Read**：`lab-batch-*.json` 单批 10 件约 9.7 MB，用脚本只打印需要的字段。

# 出处索引

| 批次 | 来源 |
| --- | --- |
| `[C]` | Codex 会话导出 |
| `[D]` | DSH 会话导出（11 月权威） |
| `[Z]` | zcode 记忆（部署 / 实验台细节权威） |

逐条原文见 `evidence/`。

# 关联页面

**实体**：[[sdp-tag-api]]、[[sdp-tag-web]]、[[tag_task]]、[[tag_callback_delivery]]、[[tag_mq_rejected]]、[[aliyun-serverless-amqp]]、[[llm-gateway]]、[[chat-judge-model]]、[[snailjob]]、[[ingress-nginx]]、[[tencent-cos]]、[[标签图谱库]]、[[lab-bench]]、[[ImageAddressPolicy]]

**概念**：[[打标四阶段链路]]、[[静默失败]]、[[假成功与严格成功判据]]、[[回调投递状态机]]、[[租约与重试上限]]、[[闸门阈值]]、[[分数带与准确率映射]]、[[评测口径一致性]]、[[环境隔离与串环境事故]]、[[发布生效三步校验]]、[[配置生效与三源优先级]]、[[分层超时]]、[[可观测性探针]]、[[浏览器存储配额]]、[[主图抓取放行模型]]、[[雪花 ID 与进程识别]]、[[排障范式]]

# Citations

- `[C]` Codex 会话导出 / `[D]` DSH 会话导出（11 月权威）/ `[Z]` zcode 记忆（部署、实验台细节权威）
