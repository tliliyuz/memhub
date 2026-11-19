# MCP 工具契约（替代 Team Brain MCP）

> 版本: 0.1
> 端点：`https://memhub.work/mcp`（Streamable HTTP）
> 鉴权：`Authorization: Bearer <device_token>`（与采集器同一鉴权体系）
> 设计原则：**读者只读、写者有界、永不硬删**。
> 适用范围：MCP 工具、参数、错误码与不变式。
> 不负责：节点字段枚举（见 [node-schema.md](node-schema.md)）、采集协议（见 [ingest-api.md](ingest-api.md)）。

## 1. 角色

| 角色 | 可用的工具组 |
|---|---|
| 任意 agent（消费者） | 检索组 |
| 治理 agent | 检索组 + 治理组 |
| CLI / 用户 | 全部（等同于治理 agent，但 canonical 变更需确认） |

服务端按 token 的 scope 裁剪 `tools/list`；agent 拿不到的工具有调用不到，而不是调用后拒绝。

## 2. 检索组

### `kb_search`
```json
{ "query": "proxy 502 根因", "project": "memory-hub", "kinds": ["pitfall","fact"],
  "tier": "canonical", "limit": 8 }
```
返回：
```json
{ "results": [
  { "id": "memory-hub/pitfall/proxy-502-two-causes",
    "kind": "pitfall", "tier": "canonical", "title": "...",
    "score": 0.83, "matched": "vector|fts|graph",
    "snippet": "…", "updated_at": "…" } ] }
```
- `tier` 默认 `canonical`；显式传 `candidate` 或 `all` 才返回候选。
- `matched` 标注命中通道，便于 agent 判断可信度。
- 无结果时返回 `results: []` 且 `hint`，不报错。

### `kb_read`
```json
{ "id": "memory-hub/pitfall/proxy-502-two-causes" }
```
返回真源全文 + frontmatter + 出边/入边（各限 20 条）+ `source` 列表。

### `kb_related`
```json
{ "id": "...", "depth": 1, "predicates": ["resolved_by","depends_on"], "limit": 30 }
```
返回邻接子图（节点摘要 + 边），供 agent 做上下文扩展。`depth` 上限 2。

### `kb_audit_list`（只读）
分页列出治理问题：`{type: contradiction|stale|orphan|low_confidence|broken_link, target, created_at}`。

## 3. 治理组

### `kb_write_candidate`
```json
{ "kind": "pitfall", "project": "memory-hub",
  "slug": "no-proxy-ipv6-httpx", "title": "...",
  "body": "## 症状\n...\n## 根因\n...\n## 解法\n...",
  "tags": ["httpx","proxy"], "evidence": ["session:...#L420-L455"],
  "edges": [{"predicate":"about","target":"component:httpx"}] }
```
- 只创建/更新 `tier=candidate`；写前做同 slug / 向量相似度检查，>0.9 时**返回冲突**（`code:3002` + 候选 id），要求改走 `kb_merge`。
- 每次写入自动 git commit（message 含 tool + 调用者）。

### `kb_propose_change`
```json
{ "id": "...", "patch": "unified diff 或 new body", "reason": "...", "evidence": [...] }
```
- 对 `tier=canonical` 节点的修改只能提案，落到 `_proposals/<uuid>.md`，等用户/CLI 批准。
- 批准后写 canonical 并保留 Change Log。

### `kb_merge`
```json
{ "source": "a1", "into": "a2", "reason": "..." }
```
- `source` 置 `tier=deprecated`、`superseded_by=into`，正文尾部保留原文，不物理删除。
- 合并前要求两节点相似度 ≥0.85 或显式 `force: true`。

### `kb_deprecate`
```json
{ "id": "...", "reason": "...", "superseded_by": "..." }
```
- 只改 frontmatter；保留文件。

### `kb_issue_resolve`
```json
{ "type": "contradiction", "target": ["a1","a2"], "resolution": "...", "action": "merge|deprecate|keep_both"}
```
- 关闭一条治理问题；`keep_both` 时必须写明为什么两者都成立（如不同环境）。

### `kb_audit`
```json
{ "scope": "memory-hub", "checks": ["contradiction","stale","orphan"] }
```
- 触发一次扫描，返回新建的问题列表。`stale` 定义：`updated_at` 超过 180 天且被引用 ≥3 次。

## 4. 错误码

| code | 含义 |
|---|---|
| 0 | ok |
| 3001 | 未找到 |
| 3002 | 冲突（相似节点已存在 / contradicts 未裁决） |
| 3003 | 权限不足（capability 不够） |
| 3004 | 校验失败（kind/枚举不符、缺必填） |
| 3005 | 该节点为 canonical，需走 propose_change |

## 5. 不变式（服务端强制）

1. 任何工具都**不能物理删除**文件。
2. `canonical` 的修改只能经 `kb_propose_change` + 批准。
3. 所有写操作必须带 `evidence`（来源引用），否则 3004。
4. 每次写产生一个 git commit；commit message 格式 `kb: <tool> <id> by <actor>`。
5. 返回给 agent 的内容默认截断到 8KB/条，超出给 `truncated: true` + `kb_read` 提示。

## 6. 迁移说明

- Team Brain MCP 的 `save_memory / search_memory / get_context` 三个旧工具**不保留兼容层**。统一映射到 `kb_write_candidate / kb_search / kb_read`。
- 旧 agent 手里的 prompt 需要一次性改写工具名；这是刻意的，避免旧语义（无 tier、无溯源）继续流入知识库。
