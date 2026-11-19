---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-2fd3bdaf
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/浏览器存储配额.md
  type: wiki
supersedes: []
tags:
- 前端
- 存储
- 评测台
tier: canonical
title: 浏览器存储配额
updated_at: '2026-11-18T07:26:22Z'
---

> saveBatch 每件重写整个 localStorage key 导致超配额，10 件≈4.61M 字符；已迁 IndexedDB，但渲染是第二瓶颈且浏览器验收未做。

# Definition

[[lab-bench]] 的存储瓶颈：旧 `labStore.ts` 的 `saveBatch` **每个商品都重写整个 localStorage key**，先丢最旧的批次，**只有当前批次自身超配额才抛错**——超配额失败因此难以察觉。

# 尺寸参考

| 场景 | 体积 |
| --- | --- |
| 全流程 10 件 | ≈ **4.61M 字符**（0.46~0.49M/件） |
| 仅标签阶段单件外推 | 1.3~2.5M 字符 |

# 现状

- **已改**：迁到 IndexedDB（`01cfd14` / `aa5f931` / `77e7d75`）。
- **⚠️ 浏览器验收仍未做**（Spec §13.3 有 6 项清单）——**不要声称已完成**。
- **第二瓶颈是渲染**：collapse 用 `v-show`、ElTabs 没有 lazy、`pretty(request)` 全量序列化 → **光改存储不够**。

# Related entities

[[lab-bench]] · [[chat-judge-model]]（评测台端到端不稳定的另一半原因）

# Common topics

- **部署/运行模型**：浏览器端配额与持久化策略（localStorage → IndexedDB）。
- **评价框架**：验收清单未完成 = 结论不可宣告。

# Citations

- 04 排障信号手册 §5.7
