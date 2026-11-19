---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/lab-admin-account
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/lab-admin-account.md
  type: wiki
supersedes: []
tags:
- 评测平台
- 弱口令
- 账号
tier: canonical
title: lab-admin-account
updated_at: '2026-11-18T07:26:22Z'
---

> 评测平台登录账号 admin/admin123（RuoYi 默认弱口令）+ 固定 client-id e5cd7e48…，tenant 000000→935515，应改。

# lab-admin-account

## Definition

[[lab-accuracy-tool]] 所连评测平台的登录账号。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 用户名 / 密码 | `admin` / `admin123` ⚠️ **RuoYi 默认弱口令** |
| client-id | `e5cd7e4891bf95d1d19206ce24a7b32e`（固定值） |
| tenant | 初始 `000000`，需切换到 `935515` |

## Relationships

- **使用方**：[[lab-accuracy-tool]]、[[lab-evaluation-framework]]
- **凭据风险**：[[credential-leak-and-rotation]]

## 已知问题

- 🟡 **`admin/admin123` 是 RuoYi 默认弱口令 + 固定 client-id**，属 superadmin 级，应改
- tenant 需手工从 `000000` 切到 `935515`，否则看不到目标数据

## Citations

- §7 评测工具（登录 / 客户端 id 行）
- §10 凭据风险汇总（🟡 中）
