---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/api-key-2e4cf8
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/对外-api-key-鉴权.md
  type: wiki
supersedes: []
tags:
- 鉴权
- API Key
- 权限模型
- 凭据风险
tier: canonical
title: 对外 API Key 鉴权
updated_at: '2026-11-18T07:26:22Z'
---

> sys_api_key 只存 SHA-256、有效期 365 天、按 scope 授权；接口为 http、无 IP 白名单、无限流——Key 即唯一凭据。

# 对外 API Key 鉴权

## Definition

sdp-tag 对外提供图谱导出等接口时使用的 API Key 鉴权机制。

## Significance

这是**唯一的安全边界**：因为接口暴露在 http 上且无任何次级防护，**Key 就是唯一凭据**——泄露即完全失守。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 存储 | `sys_api_key` 表，**只存 SHA-256** |
| 有效期 | **365 天** |
| 授权粒度 | 按 scope：`graph:export:tag`、`graph:export:relation` |
| 传输协议 | ⚠️ **http**（因 ingress 无 tls） |
| IP 白名单 | ❌ **无** |
| 限流 | ❌ **无** |

## 已泄露的 Key

`sk_5dIyx…`，名称「图谱导出-对外交付」，授予 `graph:export:tag` + `graph:export:relation`，**有效期到 2027-11-02**。

**位置**：`docs/Spec/2026-10-28-图谱接口示例.md:34`，**已核实 HEAD 里存在，`git grep` 可命中**。

**加重因素**：接口是 http、无 IP 白名单、无限流。

**历史**：作者提示过「明文 Key 会留在 git 历史里，且属于长期凭据」，用户仍要求写入。

## 处置

- 文档里改占位符 + 申请流程
- **必须真轮换**（改文档 ≠ 消除泄露，见 [[credential-leak-and-rotation]]）

## Related Entities

- [[credential-leak-and-rotation]] — 主风险清单
- [[sdp-tag-web]] — 站点只有 http，全程明文
- [[tenant-context]] — 上下文与 scope 授权
- [[aliyun-rds-instances]] — `sys_api_key` 所在库

## Common Topics

- 权限模型
- 系统架构

## Citations

- §0 P0-2
- §10 凭据风险汇总（🟠 高）
