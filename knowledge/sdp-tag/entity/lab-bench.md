---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/lab-bench
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/lab-bench.md
  type: wiki
supersedes: []
tags:
- 评测
- 平台
- 浏览器
tier: canonical
title: lab-bench
updated_at: '2026-11-18T07:26:22Z'
---

> 浏览器端评测工作台，localStorage 容量与页面渲染是两大瓶颈，已迁 IndexedDB 但浏览器验收未做。

# Definition

浏览器端评测工作台，跑批量打标/判分对比（100 件 A/B 等）。瓶颈分布在前端存储与页面渲染，而不是只有后端。

# Key attributes

- **存储瓶颈**：旧 `labStore.ts` 的 `saveBatch` 每个商品都重写整个 localStorage key → 超配额；已迁 IndexedDB（`01cfd14`/`aa5f931`/`77e7d75`），但**浏览器验收仍未做**（Spec §13.3 有 6 项清单），不要声称已完成。见 [[浏览器存储配额]]。
- **渲染瓶颈**：collapse 用 `v-show`、ElTabs 没 lazy、`pretty(request)` —— **光改存储不够**。
- **稳定性归因**：端到端不稳定先看 judge 源，见 [[chat 源 vs systemone 源（judge 对比）]]。
- **大文件**：`lab-batch-*.json` 单批 10 件约 9.7 MB，不要直接读，用脚本挑字段。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[chat-judge-model]] | 默认可能启用的 judge 源 |
| [[浏览器存储配额]] | 主瓶颈概念页 |
| [[评测口径一致性]] | 评测结论的可比性前提 |

# Citations

- 04 排障信号手册 §5.6、§5.7、§6
