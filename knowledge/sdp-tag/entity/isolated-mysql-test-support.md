---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/isolated-mysql-test-support
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/isolated-mysql-test-support.md
  type: wiki
supersedes: []
tags:
- 测试
- 数据库
- 安全守卫
tier: canonical
title: isolated-mysql-test-support
updated_at: '2026-11-18T07:26:22Z'
---

> fail-closed 测试守卫 IsolatedMysqlTestSupport，只允许 127.0.0.1 且库名前缀 sdp_tag_it_，防误删共享库；旧测试未接入。

# isolated-mysql-test-support

## Definition

集成测试的 **fail-closed 数据库守卫**，确保测试只连本地隔离库，永远不会误删共享库数据。

## Key Attributes

| 约束 | 值 |
| --- | --- |
| 允许的主机 | **仅 `127.0.0.1`** |
| 允许的库名前缀 | `sdp_tag_it_` |
| 命名差异 | `[D]` 侧叫 `sdp.integration.db.url` 强制，`[Z]` 侧叫 `IsolatedMysqlTestSupport` |
| 失败语义 | fail-closed（不满足条件直接拒绝启动测试） |

## Relationships

- **对应概念**：[[isolated-test-db-guard]]
- **保护对象**：[[aliyun-rds-instances]] 上的共享库
- **配合**：[[db-schema-change-management]]（先 apply 再发布）、[[lab-evaluation-framework]]（跑批前置）

## 已知问题

⚠️ **旧测试没有这个守卫**（`TagMqMapperIntegrationTest` 等），走的是 `application-dev.yml` 的共享库，**误跑过一次**。

## Citations

- §4.2 隔离测试库的强制约束
