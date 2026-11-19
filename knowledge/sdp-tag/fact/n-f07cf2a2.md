---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-f07cf2a2
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/隔离测试库约束.md
  type: wiki
supersedes: []
tags:
- 测试
- 数据库
- 安全守卫
tier: canonical
title: 隔离测试库约束
updated_at: '2026-11-18T07:26:22Z'
---

> fail-closed：仅 127.0.0.1 + sdp_tag_it_ 前缀，防止误删共享库；旧集成测试未接入该守卫，曾误跑共享库。

# 隔离测试库约束

## Definition

集成测试只能连接**本地隔离库**的强制约束，实现为 [[isolated-mysql-test-support]]。

## Significance

因为开发库与对方库同实例（见 [[aliyun-rds-instances]]），测试误连共享库的后果是**真实数据被删**——这不是理论风险，**误跑过一次**。

## 约束

| 项 | 值 |
| --- | --- |
| 允许主机 | **仅 `127.0.0.1`** |
| 库名前缀 | **必须 `sdp_tag_it_`** |
| 语义 | **fail-closed**（不满足即拒绝） |
| 目的 | 「以免把共享库数据删掉」 |

## 已知缺口

⚠️ **旧测试没有这个守卫**（`TagMqMapperIntegrationTest` 等），走的是 `application-dev.yml` 的共享库，**误跑过一次**。

## Related Entities

- [[isolated-mysql-test-support]] — 实现
- [[db-schema-change-management]] — 「先 apply 再发布」的另一半前置
- [[aliyun-rds-instances]] — 被保护对象
- [[lab-evaluation-framework]] — `mvn test` 默认 skip / `@Tag("dev")` 同属「跑批前置条件」

## Common Topics

- 数据流 / 部署模型
- 测试与质量保障

## Citations

- §4.2 隔离测试库的强制约束
