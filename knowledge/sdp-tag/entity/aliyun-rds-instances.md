---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/aliyun-rds-instances
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/aliyun-rds-instances.md
  type: wiki
supersedes: []
tags:
- 阿里云
- RDS
- MySQL
- 凭据风险
tier: canonical
title: aliyun-rds-instances
updated_at: '2026-11-18T07:26:22Z'
---

> 承载 sdp_tag_dev、sdp-tag-prod 及对方 sass-search-admin 的阿里云 RDS 实例（含对方独立实例），root 明文进 git。

# aliyun-rds-instances

## Definition

sdp-tag 依赖的阿里云 RDS MySQL 实例，共两组：**我方实例**与**对方 prod 实例**。

## Key Attributes

| 环境 | 主机 / 库 | 账号 / 口令 | 状态 |
| --- | --- | --- | --- |
| 我方 dev | `rm-6nn5543l26p3s153lro.mysql.rds.aliyuncs.com:3306/sdp_tag_dev` | `root` / `sx@12345…` | 🔴 明文进 git |
| 我方 prod | 同实例 `/sdp-tag-prod` | `root` / 同值 | 🔴 明文进 git 历史 |
| 对方 dev/test | 同实例 `/sass-search-admin` | `root` | 🔴 明文；**和我们的 dev 库是同一台 MySQL** |
| 对方 prod | `rm-6nnz38q794dxomh73so.mysql.rds.aliyuncs.com:3306/sass-search-admin` | `root` / `sx_dev@1…` | ⚠️ 后期 `1045 Access denied`，疑似已轮换 |
| 本地隔离测试库 | `127.0.0.1:<port>/sdp_tag_it_<name>` | `root` / 空密码 | 仅本地，见 [[isolated-test-db-guard]] |

## 隔离缺陷（必须显式记录）

⚠️ **我方 dev 库与对方 `sass-search-admin` 承载在同一台 MySQL 实例上**，且同为 `root` 账号。这既是权限隔离缺陷，也放大了凭据泄露的影响面。

## Relationships

- **凭据风险**：与 [[acr-registry]] 共用同一口令（P0-1）→ [[credential-leak-and-rotation]]
- **数据变更**：无自动迁移，靠人工 apply → [[db-schema-change-management]]
- **消费方**：[[sdp-tag-backend]]、[[sdp-tag-api]]
- **对方业务**：[[partner-brand-tenant]]

## 已知问题

- root 口令明文写在 `application-dev.yml:58` / `application-prod.yml:62`，且已进 git 历史（最后改动提交 `826b5ed`）
- 交接文档里的 `psx@…` 是**笔误**，正确是 `sx@12345…`（用错的会 1045）
- `[Z]` Git Bash 打印中文结果集是乱码 → 重定向到工作区临时文件，用 `\G` 和窄列名
- 建议 `MYSQL_PWD` 环境变量传密码，不要放命令行（会进 history 和进程列表）

## Citations

- §0 P0-1
- §4.1 连接表
- §4.2 隔离测试库的强制约束
