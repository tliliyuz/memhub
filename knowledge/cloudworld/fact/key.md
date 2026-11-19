---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/key
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/key-生命周期数据流.md
  type: wiki
supersedes: []
tags:
- 安全
- 密钥
- 数据流
tier: canonical
title: key 生命周期数据流
updated_at: '2026-11-18T07:26:22Z'
---

> key 从输入到清零经四个环节：内存缓冲 → 系统凭据库 → 请求时放入 JSON body → 临时文件即用即删。

# key 生命周期数据流

## Definition

key 生命周期数据流描述 `user_key` 在系统中经过的全部环节及其介质约束：

1. 输入 → 进程内存缓冲（用后清零）
2. → [[系统凭据库]]（加密存储）
3. → 请求时塞进 **JSON body**（见「跨文档待补」）
4. → 写临时文件时用 `--data-binary @file` 或 curl `-K` 配置，**用完即删**

全流程不上日志、不进命令行、不进仓库、不进普通配置文件。

## Significance

- 数据流末端说明 [[凭据边界]] 延伸到了**传输层**：密钥放请求体而非 header。
- 凭据库是数据流中唯一的持久化节点，其余环节均为短暂介质。
- 为 [[密钥不落盘原则]] 提供可逐环节核对的执行图。

## Related Entities

- [[系统凭据库]] — 数据流中唯一的持久化节点。
- [[凭据模块]] — 第 1→2 环节的实现（写入）。
- [[桌面登录入参]] — 第 1 环节的内存缓冲与清零。
- [[配置文件 config.toml]] — 明确不在数据流上的介质。

## Common Topics

- **数据流**：输入 / 持久化 / 传输 / 临时落地四段。
- **安全机制**：每段对应的介质约束见 [[密钥不落盘原则]]。

## 跨文档待补

第 3 环节「JSON body 传参」的细节来自**接口篇（header 不够）**，该文档尚未摄入。待接口文档入库后，需在此回填链接并补充：为何 header 不足、body 字段命名与请求结构。
