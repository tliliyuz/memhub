---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/unified-node-kind-enum
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- data-model
- schema
- enum
- graph
tier: candidate
title: 统一节点模型：单表 + kind 枚举 + entity_kind 二级枚举 + 边枚举
updated_at: '2026-11-18T10:56:54.868098Z'
---

不把“事实节点”和“实体+关系”做成两套结构，而是同一节点表靠枚举区分语义：Node 字段为 id、kind、title、content、confidence（决定是否进复核队列）、source{type,path,locator} 溯源、valid_from/valid_until 时间语义、entity_kind（仅 kind=entity 时用）。kind 固定枚举：entity、fact、decision、procedure、pitfall、preference、event、question。entity_kind 枚举：service、component、concept、tool、person、team、project、external_system、config、other。边也定枚举：结构类 part_of、depends_on、exposes、runs_on；知识类 about（fact/pitfall→entity）、resolved_by（pitfall→procedure）、supersedes（新决策→旧决策）、evidenced_by（节点→源片段）、contradicts。kind/边为 schema 强约束，LLM 只能从枚举中选，不允许自由发挥；同一个 LLM 调用同时产出节点与边；检索可按 kind 过滤（如只取 procedure），浏览按边展开。
