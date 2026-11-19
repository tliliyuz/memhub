---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/oss
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/主图-oss-转存.md
  type: wiki
supersedes: []
tags:
- 图片
- OSS
- 成本
tier: canonical
title: 主图 OSS 转存
updated_at: '2026-11-18T07:26:22Z'
---

> 2026-10-22 合入的主图转存能力，主图输入带来 +68~85 个正确标签，但 RL tokens +58.8%。

# 定义

主图 OSS 转存是把商品主图转存到 OSS 以供模型读取的能力，2026-10-22 合入。

# 关键属性

| 属性 | 值 |
| --- | --- |
| 合入日期 | 2026-10-22 |
| 效果 | 主图输入带来 **+68~85 个正确标签** |
| 成本 | RL tokens **+58.8%** |
| 配套开关 | lab 侧 `includeMainImage=true` 固定（10-26） |

# 关系

- 下游：[[商品打标实验台]]（`includeMainImage=true` 与主图转存是同一输入的上下游）
- 下游：[[正式打标链路]]
- 性能口径：token 增幅须按 [[性能与成本基线]] 标注「单件/整批、含不含图片下载」

# 注意

「前端隐藏了 includeMainImage 选项」不等于该输入被关闭——按 [[仲裁口径]] 规则 1，以代码/配置为准。

# Citations

- `00-时间线与仲裁口径.md` §1 时间线 10-22、10-25、10-26 条目
