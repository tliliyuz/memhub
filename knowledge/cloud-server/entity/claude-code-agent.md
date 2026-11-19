---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloud-server/entity/claude-code-agent
kind: entity
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/entities/claude-code-与-agent-客户端.md
  type: wiki
supersedes: []
tags:
- 角色
- 客户端
- 调用方
tier: canonical
title: Claude Code 与 Agent 客户端
updated_at: '2026-11-18T07:26:22Z'
---

> 记忆注入链路的调用方，经 127.0.0.1:8096 访问 tdai-proxy，目前依赖 SSH 隧道。

# Claude Code 与 Agent 客户端

## 定义

使用记忆能力的开发侧客户端（Claude Code 或其他 Agent），是 [[记忆栈服务拓扑]] 中"注入链路"的起点。

## 关键属性

- 访问方式：`127.0.0.1:8096` → [[tdai-proxy]]，即必须先把远端端口隧道到本地（SSH 隧道）。
- 不直接接触面板（8125）与 core（8420）。
- 链路：客户端 → [[tdai-proxy]] → [[magpie gateway]] → [[上游模型供应商]]。

## 关系

- 是 8096 不做公网暴露这一决策的直接受影响方；待办 4 计划用子域名 + [[nginx]] 反代鉴权改善。
- 与 [[浏览器用户]]、[[管理员账号]] 分属不同使用面。

## Citations

- `cloud-server.md` —— 见 [[cloud-server 运维快照]]。
