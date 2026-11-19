---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-dda7a473
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/隔离测试.md
  type: wiki
supersedes: []
tags:
- 测试
- 隔离
- 配置安全
- 凭据
tier: canonical
title: 隔离测试
updated_at: '2026-11-18T07:26:22Z'
---

> 用一次性 profile / 隔离目录跑完整链路，避免污染生产配置，并规定凭据不落盘与配置还原顺序。

# 隔离测试

## 定义

在不污染生产配置的前提下验证完整链路：使用一次性 profile（如 `demo` 或独立目录）运行，并对凭据缺失、配置还原、构建产物路径等副作用做出显式安排。

## 意义

- 是 [[验收证据分层]] 中「可采信的通过项」的前提：隔离环境跑出的通过项才不掺杂对生产状态的改变。
- 两套诊断结果即为证据：隔离 profile `ok 13 / warn 5 / fail 0`、生产 `ok 16 / warn 2 / fail 0`；隔离环境的 WARN 全为「未连接 + dev_resolve」这类预期项。

## 机制要点

| 关注点 | 做法 |
| --- | --- |
| profile | 一次性 profile / 隔离目录，跑完即弃 |
| 凭据 | 无效 key → `valid=false`，**且目标目录未被创建**（不落盘、不存凭据） |
| 断开顺序 | **先还原 `settings.json`（删除 `apply` 创建的文件）再停 relay**，否则留下指向已停 relay 的配置 |
| 构建输出 | 输出到 `target-build\`，避免替换被 watchdog 占用的 `target\debug\cloud-world.exe` |
| 事后确认 | 用 `status` 确认生产 [[本地 relay]] 仍在运行、bridge 端口正常 |

## 关联

- 被测主体：[[cloud-world 桌面端]]
- 隔离对象：[[本地 relay]] 的生产实例
- 验证路径：[[真实请求链路]]

# Citations

- [[08-验收证据分层]]
