---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-aaa0a80e
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/other/信封响应格式.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: 信封响应格式
updated_at: '2026-11-18T07:26:22Z'
---

# Definition

[[memhub 云端面板 API]] 部分端点采用的统一外壳：

```
{ "code": 0, "message": "...", "request_id": "...", "data": { ... } }
```

- `code`：业务/协议状态码（`0` 表示外壳层成功，`401` 表示凭据无效等）。
- `message`：可读描述。
- `request_id`：请求标识，用于链路追溯与服务端定位。
- `data`：真实业务载荷，**内层形状由端点/action 决定**。

# Significance

- **外壳统一 ≠ 载荷统一**：[[meta-action 端点族]] 内各 action 的 `data` 形状各自不同，因此信封只解决了「元信息在哪」，未解决「业务字段长什么样」，见 [[响应形状三分法]]。
- **`code=0` 不等于业务成功**：[[meta-auth-verify 端点]] 的无效 key 返回 `200 + code=0 + valid=false`，业务结论在 `data.valid` 内，见 [[无效凭据语义分裂]]。
- **`request_id` 的价值**：跨端点的排查无需猜测，直接用 `request_id` 关联日志，见 [[phase-b 端点证据文档]]。

# Related Entities

- 使用方：[[meta-auth-verify 端点]]、[[meta-action 端点族]]
- 不使用方（对比）：[[auth-user-key-login 端点]]（裸扁平 JSON）、[[meta-instances 端点]]（裸 JSON）
- 实现：[[cloud-api-crate]]

# Common Topics

- 数据流：外层元信息与内层载荷分离解析。
- 系统架构：观测性（`request_id`）随协议外壳一并下发，降低排障成本。
