---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: cloudworld/entity/memhub
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/memhub-云端服务.md
  type: wiki
supersedes: []
tags:
- memhub
- 服务端
tier: canonical
title: memhub 云端服务
updated_at: '2026-11-18T07:26:22Z'
---

> memhub 面板 API 背后的服务端系统本体；与客户端封装 cloud-api-crate 相对。

# Definition

对外提供的 memhub 云端系统本体，是 [[memhub 云端面板 API]] 的服务端实现方。本来源仅从调用方视角记录了它的接口形态，服务端内部架构暂无资料。

# Key Attributes

- **暴露面**：通过 [[memhub 云端面板 API]] 的四类端点对外提供能力（实例清单、凭据校验、资产列举、登录态换取）。
- **服务端侧约束的可见证据**：无效 key 在不同端点上返回不同状态码/`code`，说明端点的鉴权实现分支并不统一，见 [[无效凭据语义分裂]]。
- **租户隔离**：服务端以 [[x-tdai-service-id]] 与 [[team_id]] 两个维度共同确定请求范围，见 [[租户双维度模型]]。

# Relationships

- 对外接口面：[[memhub 云端面板 API]]
- 客户端：[[cloud-api-crate]]
- 待补充：服务端内部模块划分、部署模型（当前无来源文档）
