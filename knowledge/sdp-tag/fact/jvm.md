---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/jvm
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/容器内存按-jvm-参数推导.md
  type: wiki
supersedes: []
tags:
- 资源
- JVM
- 部署
tier: canonical
title: 容器内存按 JVM 参数推导
updated_at: '2026-11-18T07:26:22Z'
---

> MaxRAMPercentage=70 使 3Gi limit 只剩约 2.1Gi 堆，峰值 5.0Gi 实测后定为 6Gi limits、requests 不变。

# 定义

容器内存 limit 不能按「应用需要多少堆」直觉配置，必须按 JVM 参数反推：

> `MaxRAMPercentage=70` 意味着 `limit=3Gi` 时**堆上限只有约 2.1Gi**。加上 Metaspace、线程栈、ZGC 和直接内存约 0.7Gi，正好等于观察到的常驻 2.8Gi。只提到 4Gi 非堆余量只剩 1.2Gi，还是会贴着上限。

# 实测

- 跑批峰值 **5.0Gi**，空闲回落 1.0Gi。
- 3Gi 配置下曾 **3020/3072 OOMKilled（exit 137）**。

# 结论

取 **limits = 6Gi**，`requests` **不变**（保留调度弹性），只提 limits。

# 关联

- 相关实体：[[部署环境]]、[[打标系统]]
- 相关概念：[[镜像经 pod 中转]]

# Citations

- `02-方案选型与权衡.md` §22
