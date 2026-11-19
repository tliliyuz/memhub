---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/meta-auth-verify
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/meta-auth-verify-端点.md
  type: wiki
supersedes: []
tags:
- memhub
- api
- 端点
- 鉴权
tier: canonical
title: meta-auth-verify 端点
updated_at: '2026-11-18T07:26:22Z'
---

> POST /api/v1/meta/auth/verify，信封响应、data 内嵌 {valid,user}；无效 key 返回 HTTP 200 且 valid=false。

# Definition

[[memhub 云端面板 API]] 中的凭据校验端点：`POST /api/v1/meta/auth/verify`。用于判定给定 [[user_key]] 是否有效，并返回对应用户信息。

# Key Attributes

- **响应形状**：[[信封响应格式]]（`{code, message, request_id, data}`），`data` 内再嵌套 `{valid, user}`。
- **无效 key 表现**：**HTTP 200 + `code=0` + `valid=false`**。这不是错误，而是一次成功的「校验结果为否」，是 [[无效凭据语义分裂]] 的核心例证。
- **分支判定要求**：客户端必须以 `valid` 布尔值分支，不能按 HTTP 状态码判定鉴权结果。
- **身份参数**：从请求 **body** 读取 `user_key`（见 [[身份参数载体约束]]）。
- **链路追溯**：响应中的 `request_id` 可用于问题定位与日志关联。

# Examples

调用形态（curl，key 经 curl 配置文件传入，避免命令行泄露，见 [[凭据安全处理实践]]）：

```bash
curl -K verify.conf -X POST https://<host>/api/v1/meta/auth/verify \
  --data-binary @body.json   # body: {"user_key":"<key>"}
```

判读要点：`valid=false` → 走「凭据无效」业务分支；HTTP 200 本身不代表鉴权通过。

# Relationships

- 父级：[[memhub 云端面板 API]]
- 概念：[[信封响应格式]]、[[无效凭据语义分裂]]、[[身份参数载体约束]]
- 对比：[[meta-action 端点族]]（同一无效 key 返回 `401 code=401`）
- 代码：[[cloud-api-crate]] 的 `verify_user_key`
- 证据：[[phase-b 端点证据文档]]
