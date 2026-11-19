---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/n-c9c90b4b
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/图谱导出接口.md
  type: wiki
supersedes: []
tags:
- 导出
- 接口
- 契约
tier: canonical
title: 图谱导出接口
updated_at: '2026-11-18T07:26:22Z'
---

> 对外导出标签图谱的接口，刻意返回裸契约信封而不套 R<T>，version 取四表 max(update_time)。

# 定义

图谱导出接口把 [[标签图谱]] 的全量数据导出给调用方（含 API Key 场景）。

# 关键属性

- **裸契约信封**：直接返回 `{datas, resp_code, resp_msg, root_tag, version}`，不套项目统一 `R<T>`，见 [[裸契约信封]]。
- **version 语义**：取四张图谱表 `max(update_time)`，不是导出日期或版本号——「数据没变版本不变」。
- **按行业嵌套不拍平**：标签字典 key 只有 `UPPER(标签名)`，拍平会跨行业覆盖。
- **校验策略**：整次失败并报 id，不静默丢弃。
- **鉴权**：API Key 走权限码，类上没有 `@SaCheckRole`，见 [[API Key 鉴权权限模型]]。

# 关系

- 读取 [[标签图谱]]；鉴权模型见 [[API Key 鉴权权限模型]]。

# Citations

- `02-方案选型与权衡.md` §25、§26
