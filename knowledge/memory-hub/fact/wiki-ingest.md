---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/wiki-ingest
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/wiki-ingest-加工管线.md
  type: wiki
supersedes: []
tags:
- 加工管线
- Wiki
tier: canonical
title: Wiki Ingest 加工管线
updated_at: '2026-11-18T07:26:22Z'
---

> 上传源材料 → 抽取（默认并发 3）→ 页面合并与重写（单 Wiki 串行），模型调用上限由所有 Wiki 共享为 5，并给出规模/耗时快照以说明其成本。

# 定义

Wiki Ingest 是把源材料加工为 [[Wiki]] 页面的管线，由 [[Memory Hub]] 触发。

# 流程

```text
上传选定源材料 → 抽取（默认并发 3）→ 页面合并与重写（单 Wiki 串行）→ Wiki 就绪可分配
```

# 并发与配额

| 项 | 值 |
| --- | --- |
| 抽取默认并发 | 3 |
| 模型调用上限 | 5（**所有 Wiki 共享**） |
| 页面合并与重写 | 单 Wiki **串行** |

# 规模快照（`sdp-tag` Wiki）

| 指标 | 数值 |
| --- | --- |
| 输入 | 5 份会话 Markdown + 1 份导出索引，约 263 KiB |
| 生成页面文件 | 约 421 KiB |
| 含原文与索引的 Wiki 目录 | 约 2.75 MiB |
| 数据库页面记录 | 170 页，状态仍为 `processing` |

> 该组数字是**加工中的快照**，不代表最终规模。

# 意义

- 说明 Ingest 是**重成本、异步**的加工过程：并发受共享配额约束，单 Wiki 内串行，状态需轮询。
- 解释了为什么 Wiki 需"就绪后"才能分配。

# 相关实体

[[Memory Hub]]、[[Memory Knowledge]]、[[Wiki]]、[[SDP Tag 项目]]

# Citations

- `tencentdb-agent-memory-session.md`
