---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/tencentdb-agent-memory-sdp-tag
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/sources/tencentdb-agent-memory-本地部署与-sdp-tag-使用记录.md
  type: wiki
supersedes: []
tags:
- 部署
- 记忆平台
- 客户端接入
- 排障
tier: canonical
title: TencentDB Agent Memory 本地部署与 SDP Tag 使用记录
updated_at: '2026-11-18T07:26:22Z'
---

> TencentDB Agent Memory 在 Windows 本机的部署拓扑、SDP Tag 记忆组织、DSH/Codex 客户端接入、三类资产使用方式、Wiki 加工快照与一次 DSH 502 排障记录。

# 概述

本文是一份**部署与使用记录**（非需求或设计文档），记录 [[TencentDB Agent Memory]] 在 Windows 本机的落地方式，以及 `applesay` 团队下 [[SDP Tag 项目]] 的记忆组织实践。

# 要点

## 本地部署

- 仓库位于 `D:\workplace\TencentDB-Agent-Memory`（浅克隆的默认分支 `feat/server_team`，提交 `2002196`）。
- Windows 部署脚本副本与本地配置位于 `D:\workplace\TencentDB-Agent-Memory-local`；运行 `start-local.sh` 需要 Git Bash 与 Docker Desktop。
- 四端口：Hub 8125（面板）、Core 8420、Knowledge 8424、Proxy 8096，仅绑定本机回环地址 → 见 [[本地部署拓扑与回环绑定]]。
- [[Memory Core]] 默认使用 SQLite，数据持久化在 Docker 卷 `tdai-memory-core-data`；[[Wiki]] 与知识索引由 [[Memory Hub]] 管理。
- 上游为 [[applesay 上游模型服务]]（`https://applesay-api-hup.applesay.cn/v1`，模型 `deepseek-v4.1-flash-1017`）；客户端只持有 Memory 的 `user_key` → 见 [[凭据分层模型]]。

## 记忆组织

- 团队 `applesay`，项目记忆归属 `sdp-tag-doc`；实际执行任务的是 [[DSH Desktop]] 或 [[Codex Desktop]]，[[Memory Agent]] 决定读取与沉淀哪份记忆 → 见 [[项目记忆归属与 Agent 分配]]。
- 只积累仓库里没有的内容（业务术语、决策背景、排障经验、被验证的工作方法）；设计/开发文档继续以源码仓库为准 → 见 [[记忆沉淀策略]]。
- 同一项目的开发、排障、评测可共用一个 Memory Agent；需要隔离时再拆分。团队可见的 Chat Memory 必须分配给另一个 Agent 才能作为其运行时记忆。

## 客户端接入

- [[DSH Desktop]]：内置提供商 `deepseek-official`，Base URL `http://127.0.0.1:8096/dsh/default`（不加 `/v1`），凭据填 `user_key`，模型 `deepseek-v4.1-flash-1017`（旧名 `deepseek-flash` 曾被上游拒绝）；新开会话在初始化表单选择 `applesay → sdp-tag-doc`。已验证表单与模型回复跑通。
- 切换 Agent：同一会话内需单独发送 `mem:session-reset` 再重选 → 见 [[会话重置与 Agent 切换]]。
- 自定义提供商可转发模型请求，但缺少 Memory 绑定所需的 DSH 会话 ID，轨迹落在 `_unassigned`；自动归档应使用内置提供商。
- [[Codex Desktop]]：保留 OpenAI 官方供应商，直连不经过 Proxy；用 [[Codex 会话导入工具]] 导入历史会话，由 Memory 提炼。`memory` profile 仅验证过 CLI 链路；**未验证**桌面端经 Proxy 归档，**无**自动同步配置。
- 本机已导出 108 个 SDP Tag 相关 Codex 会话为 Markdown，索引位于 `D:\workplace\codex-sdp-tag-sessions\README.md`。Markdown 导出与导入 Chat Memory 是独立操作。

## 三类资产

| 资产 | 对话中怎么用 | 怎么更新 |
| --- | --- | --- |
| [[Chat Memory]] | Proxy 提供 L3 长期画像与 L2 场景索引，Agent 按需下钻 L2 正文、L1 原子记忆、L0 原始会话 | 绑定会话满足条件时自动提炼，也可导入历史；新证据可更新同一 L2 场景，时间流逝本身不触发更新 |
| [[Wiki]] | Agent 搜索已分配 Wiki，再读取命中页面 | 上传选定源材料触发 [[Wiki Ingest 加工管线]]；面板要求 Wiki 就绪后才能分配；会话记忆不会自动写入 Wiki |
| [[Skill]] | Proxy 提供可用列表，Agent 用到时读取完整步骤 | 可从会话中提炼，适合可重复的排查/验证/操作流程 |

[[Code Graph]] 用于预索引符号与调用关系；DSH 能直接读取当前工作目录，当前可先跳过。

→ 整体见 [[三类资产模型]]。

## Wiki 加工观察

`sdp-tag` Wiki 曾上传 5 份会话 Markdown + 一份导出索引，原文约 263 KiB。抽取默认并发 3，所有 Wiki 共享模型调用上限 5，单 Wiki 的页面合并与重写串行。一次测量：生成页面文件约 421 KiB，含原文与索引的 Wiki 目录约 2.75 MiB，数据库记录 170 页且状态仍为 `processing`——属加工中的快照数据。

## DSH 间歇性 502

- 现象：DSH 显示 `DeepSeek Messages request failed (502)`，重试有时恢复。
- Proxy 日志：失败发生在转发上游 `/v1/messages` 时，多次约 10.4 秒后记录 `fetch failed`，随后 Proxy 返回 502。
- 检查时三个容器健康，日志未显示 HTTP 429；容器内四次无凭据探测均快速收到预期 401（仅证明探测当时可达）。
- 结论：故障段已收敛到 Proxy → 上游；现有日志无连接异常底层原因，**无法细分 DNS / TCP·TLS / 网关断连**。→ 见 [[Proxy 转发故障分段定位]]。

# 未验证 / 未结论项

- Codex 桌面端通过 Proxy 归档：未验证。
- Codex 自动同步：未配置。
- `memory` profile：仅验证过 CLI 链路。
- 502 根因：未细分定位。

# Citations

- 源文档：`tencentdb-agent-memory-session.md`
- 相关页面：[[TencentDB Agent Memory]]、[[Memory Hub]]、[[Memory Core]]、[[Memory Knowledge]]、[[Memory Proxy]]、[[applesay 上游模型服务]]、[[DSH Desktop]]、[[Codex Desktop]]、[[Memory Agent]]、[[SDP Tag 项目]]、[[applesay 团队]]、[[Codex 会话导入工具]]、[[本地部署拓扑与回环绑定]]、[[凭据分层模型]]、[[记忆分层 L0–L3]]、[[项目记忆归属与 Agent 分配]]、[[记忆沉淀策略]]、[[三类资产模型]]、[[Chat Memory]]、[[Wiki]]、[[Skill]]、[[Wiki Ingest 加工管线]]、[[Code Graph]]、[[会话重置与 Agent 切换]]、[[Proxy 转发故障分段定位]]
