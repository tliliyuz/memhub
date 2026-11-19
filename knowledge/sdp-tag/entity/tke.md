---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/tke
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/tke-集群.md
  type: wiki
supersedes: []
tags:
- 部署
- k8s
- 基础设施
tier: canonical
title: TKE 集群
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-10-26~29 的打标部署载体，承载 api / web / snailjob；deploy/k8s/api.yaml 的 env 不覆盖阈值。

# 定义

TKE 集群是打标系统的容器运行环境，2026-10-26~29 完成部署。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 部署时间 | 2026-10-26 ~ 10-29 |
| 工作负载 | `api`、`web`、`snailjob` |
| 配置清单 | `deploy/k8s/api.yaml` |

# 重要约束

`deploy/k8s/api.yaml` 的 env **没有覆盖阈值**——改 yaml 不会改阈值。阈值由配置键决定（见 [[阈值分层]]：`tag.lab.label-threshold` 0.7 / `tag.pipeline.label-threshold` 0.9）。

# 成员说明

- `api`：打标服务入口（承载 [[正式打标链路]]）
- `web`：前端服务（「场景 → 行业」术语改动的展示层落点，提交 `288d0b3`）
- `snailjob`：调度组件

三者目前仅作为该部署清单中的成员出现，暂无独立身份，故并入本页。

# 关系

- 运行 [[正式打标链路]]、[[MQ 消费链路]]
- 环境类问题的适用范围：按 [[仲裁口径]] 规则 2，环境/网络问题（如 ACR 上传带宽、docker push 被代理掐断）只在当时环境有效，换机器/换网络需重测

# Citations

- `00-时间线与仲裁口径.md` §1 时间线 10-26~29 条目；§3 错 4；§2 规则 2
