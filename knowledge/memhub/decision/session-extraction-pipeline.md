---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/decision/session-extraction-pipeline
kind: decision
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- pipeline
- llm-extraction
- cost-control
tier: candidate
title: 会话类数据源的四级抽取管线（筛选→价值判断→提炼→归并）
updated_at: '2026-11-18T10:56:54.868098Z'
---

会话目录（几十到几百 MB 的 JSONL、分钟级追加、工具输出/报错/重复读文件占 95%+ 信噪比）不能直接全量喂 LLM 抽取。管线分四级：1) 筛选层（零成本）只读上次水位后追加的 jsonl，解析 user 消息、assistant 文本块、错误摘要，丢弃工具结果正文；2) 价值判断层（便宜模型）判断片段是否含值得沉淀内容（决策、踩坑、被验证的方法、偏好），多数片段直接丢弃；3) 提炼层（贵模型）只对通过筛选的片段做结构化抽取，入图带溯源 source=会话id+行号；4) 归并层把同主题的多次出现合并更新同一节点，而非堆叠相似节点。成本估算：每天 10 个活跃会话、每会话 5-10 个有价值片段，约 50-100 次提炼调用。
