---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/taglabproperties
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/taglabproperties.md
  type: wiki
supersedes: []
tags:
- 配置
- 实验台
- 模块
- 开关
tier: canonical
title: TagLabProperties
updated_at: '2026-11-18T07:26:22Z'
---

> 实验台配置属性类，其 labelMergeEnabled 是确实生效的活开关（默认 false）。

# Schema

- **kind**: module
- **职责**：承载实验台的配置属性，绑定 yml 中的实验台相关开关。

# Definition

`TagLabProperties` 是实验台的配置属性类。本文只贡献一条确定事实：`labelMergeEnabled` **确实被代码使用**，是活开关，默认 `false`。

# 关键属性

| 项 | 内容 |
| --- | --- |
| 活开关 | `labelMergeEnabled` |
| 默认值 | `false` |
| 影响面 | 标签合并/合批行为（见 [[打标阶段演进]]） |

# 冲突与裁决

**A3：`label-merge-*` 是活配置还是死字段？**

| 说法 | 来源 |
| --- | --- |
| 「gated/回执只剩死字段与死配置（含 `label-merge-*` yml）」 | `[D]` 11-05 只读快照 |
| 「`label-merge-*` 是活配置」（`TagLabProperties.labelMergeEnabled` 真被用） | `[D]` 11-04 实现 |

**裁决：以代码为准——它是活的开关，默认 `false`。**

**方法论启示**：只读快照（11-05）把「未被当前链路触发」误判为「死配置」，而同批更早的实现记录（11-04）才是对的。这类判断必须回到代码调用点，而不是看配置是否被引用为字符串。见 [[时间线仲裁口径]]。

# Relationships

- [[打标阶段演进]] — 合并/合批行为属于阶段内的批处理细节。
- [[TagWorkflowService]] — 阶段编排方。

# Citations

- 源：`06-未决与空白.md` A3
