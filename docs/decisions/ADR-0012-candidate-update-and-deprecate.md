# ADR-0012 候选区闭环：允许更新与废弃自己的候选

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-23 |

## 背景

ADR-0011 把 MCP 写能力收窄到 `kb_write_candidate` 一个工具，明确写了「更新已有候选留到批准流落地后再放开」。实际使用中这个限制的代价比预期高：写候选的 agent 在提交后常发现自己写错了结论、漏了条件或标题不准确，而它唯一的手段是换一个 slug 再写一遍，把错的那条留在候选区。slug 冲突与正文哈希去重又让「换 slug 重写」这条路时灵时不灵，结果是候选区里同时存在正确与错误的重复条目，治理成本反而增加。另一方面，`tier=candidate` 本身不是权威结论：候选区的写入本来就不需要批准流，`kb_write_candidate` 已经建立了「凭据有界 + 只碰候选 + 服务端 git commit」这一套边界。把同一条边界延伸到「修改自己的候选」，没有引入新的信任面。

## 决策

新增 `kb_update_candidate` 与 `kb_deprecate`，补齐候选区的写闭环，仍然完全不碰 canonical。本条取代 ADR-0011 中「更新已有候选留到批准流落地后再放开」一句；ADR-0011 的其余边界继续有效。

- **作用域不变**：两者都要求 `mcp:write`；`tools/list` 现在对 `mcp:write` 返回七个工具，对 `mcp:read` 仍是四个。不新增作用域。
- **只作用于 candidate**：节点当前 `tier` 必须是 `candidate`；命中 `canonical` 或 `deprecated` 返回 `409/1010`、`data.reason=not_candidate`，文件不改。这样即使某个节点在两次调用之间被管理台转正，写工具也不可能顺着 id 改到 canonical。
- **乐观并发前置条件**：两个工具都必须带 `expected_revision`。修订号就是现有 `manage.node_revision` 的取值（文件内容 sha256 前 16 位），`kb_read` 现在直接返回它，调用方不需要另设查询。检查与写入在同一个跨进程写锁内完成。不符返回 `409/1010`、`data.reason=revision_conflict`。
- **更新范围**：只允许 `title`、`body`、`tags`、`confidence`。`kind`、`slug`、`id`、`tier`、`source`、`created_at` 不可改——改 slug 等于换节点，那是创建语义，不属于更新。更新后对标题与正文重跑创建时的内容门槛；改正文时对同项目其他候选重跑归一化正文哈希去重。
- **废弃**：`tier` 置 `deprecated`，文件保留，`reason` 写入 frontmatter 的新字段 `deprecated_reason` 并追加 `## 废弃说明` 到正文末尾。`superseded_by` 可选。
- **契约放宽一处**：`NodeFrontmatter` 原先要求 `tier=deprecated` 必须有 `superseded_by`。候选区最常见的废弃情形恰恰是「这条结论是错的，没有东西取代它」，硬造一个指向自己的 `superseded_by` 会污染真源。改为「`superseded_by` 或 `deprecated_reason` 至少一项」，两者都没有仍拒绝。
- **不新增能力**：不物理删除，不写 canonical，不做合并与转正；`kb_propose_change`、`kb_merge`、`kb_issue_resolve`、`kb_audit` 与批准流仍关闭。

## 备选与否决理由

- 用 `kb_write_candidate` 加 `mode: update` 开关：同一个工具两种语义，参数校验与错误码会分叉，`tools/list` 也表达不出「这个工具会改已有节点」。拆成独立工具更清楚。
- 更新强制带 `evidence`：证据属于「这条知识从哪来」的事实，更新只改表述时没有新证据可给，强制会逼调用方伪造引用。证据仍在创建时必填且不可通过写工具改变。
- 废弃必须给 `superseded_by`（维持原契约）：候选区大量废弃是「结论错误、无替代」，强制会产出自我引用或假指向的脏数据。
- 允许写工具直接把候选转成 canonical：转正是治理动作，需要人工确认与批准流落点，不在本次范围。

## 后果

- agent 可以修正自己写错的候选，而不必留下错副本；候选区的重复与误导条目会减少。
- 写工具从 1 个变成 3 个，`mcp:write` 暴露面变大；缓解手段是「只碰 candidate + revision 前置条件 + 原有内容门槛与去重」。
- 真源多了一个可选 frontmatter 字段 `deprecated_reason`。旧节点不含该字段仍可读；只在用新工具废弃时才写入。
- 无法阻止同一 agent 反复改写自己刚写的候选；限制是每日创建上限（50 次）与 revision 冲突，写工具本身不另设更新频率上限。若实际出现刷写，再按凭据加更新配额。
- 转正与合并仍待批准流；本次不推进该项。
