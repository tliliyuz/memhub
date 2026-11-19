---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-35a57cbb
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/实测口径.md
  type: wiki
supersedes: []
tags:
- 测试
- 度量
- 验收
- 可复核性
tier: canonical
title: 实测口径
updated_at: '2026-11-18T07:26:22Z'
---

> 测试数、耗时、字节数等可数量必须来自当次运行输出，不得沿用上一轮或文档中的旧值。

# 实测口径

## 定义

对**可以数出来的量**——测试通过数、请求耗时、产物字节数、诊断计数——一律以**当次运行输出**为准，不得沿用上一轮记录或 README 中的历史值。

## 意义

- 支撑 [[验收证据分层]]：通过项只有可复核才算证据；口径漂移会让整份报告失去可信度。
- 反例：README 曾写「74 个测试」，2026-11-12 实测为 **73**。

## 2026-11-12 的实测值

| 项 | 值 | 归属 |
| --- | --- | --- |
| `cargo build` | 无警告 | [[cloud-world 桌面端]] |
| `cargo test --workspace` | 73 passed, 0 failed | 同上（分布见下） |
| 前端 JS | 242 kB / 75 kB gzip | 同上 |
| 真实请求 | HTTP 200 / 1685 ms / `"pong"` | [[真实请求链路]] |
| 诊断（隔离 profile） | ok 13 / warn 5 / fail 0 | [[隔离测试]] |
| 诊断（生产） | ok 16 / warn 2 / fail 0 | [[cloud-world 桌面端]] |
| 资产 | 85 条可见 | 同上 |

测试分布：core 29 · api 14 · relay 5 + 集成 16 · service 5 · cli 2 · desktop 2。

## 关联

- 数值归属载体：[[cloud-world 桌面端]]
- 约束对象：[[验收证据分层]]
- 原始出处：`docs/evidence/2026-11-12-desktop.md`

# Citations

- [[08-验收证据分层]]
