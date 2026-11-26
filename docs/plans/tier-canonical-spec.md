# 取消候选门槛：实施规格

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified（承接负责人 2026-11-26 裁决） |
| 最后更新 | 2026-11-26 |
| 适用范围 | worker 合并、检索默认层、MCP 写工具的创建者边界、管理台 tier 写入、存量数据迁移、验收条件 |
| 不负责 | 架构裁决（见 [ADR-0014](../decisions/ADR-0014-drop-candidate-tier-gate.md)）、节点字段契约（见 [node-schema.md](../contracts/node-schema.md) §5）、MCP 工具契约（见 [mcp-tools.md](../contracts/mcp-tools.md) §1） |

## 1. 目标与范围

承接 [ADR-0014](../decisions/ADR-0014-drop-candidate-tier-gate.md)：取消「候选需人工转正」门槛。所有新写入的节点直接是 `canonical`，默认检索可见；`deprecated` 保留用于事后废弃；`candidate` 只作为历史枚举值存在，没有任何写入路径。

### 1.1 本轮范围

- worker 合并直接写 `canonical`，对已有节点不再因层级跳过，沿用追加式合并。
- 检索默认排除 `deprecated`；`tier` 参数收敛为 `canonical` / `all`。
- MCP 的 `kb_update_candidate` / `kb_deprecate` 从「只碰 candidate」改为「只碰创建者自己的节点」。
- 管理台新建与更新默认写 `canonical`，显式 `tier=candidate` 拒绝。
- 存量 `candidate` 行的一次性迁移与 `kb_node_revisions` 记录。

### 1.2 不在本轮

- 删除 `tier` 列或 `candidate` 枚举值。
- 新增审批流、质量闸门或 LLM 自动复核（ADR-0014 方案 A 已否决）。
- 历史 `deprecated` 节点的批量恢复。
- `kb_search` 的向量检索。

## 2. 行为规格

### 2.1 写入层级

| 入口 | 行为 |
|---|---|
| worker 抽取（`worker/merge.py`） | 新节点写 `tier=canonical`；已有节点（任意层级）继续合并：追加新来源、合并标签、补 `## 补充（日期）`，不覆盖标题。不再产生「跳过 canonical」的计数 |
| MCP `kb_write_candidate` | 创建 `tier=canonical`；工具名不改 |
| 管理台 `POST /api/v1/kb/nodes` | `tier` 缺省 `canonical`；显式 `candidate` 返回 `422/1012` |
| 管理台 `PUT /api/v1/kb/nodes/{id}` | `tier` 允许 `canonical` / `deprecated`；显式 `candidate` 返回 `422/1012` |
| 管理台 `POST .../deprecate` | 不变，写 `tier=deprecated` |

存储层（`KnowledgeStore.write` / `PgKnowledgeStore.write`）仍接受任意合法 `Tier`：迁移工具与测试夹具需要写入历史层级，门禁不在存储层。

### 2.2 检索

- `query.search` 的 `tier` 只接受 `canonical`（默认）与 `all`；其他值（含 `candidate`）返回 `QueryError`（MCP `3004`，管理台 `422`）。
- `canonical`：返回所有非 `deprecated` 节点（包含历史存量 `candidate`，直到迁移完成）。
- `all`：包含 `deprecated`。
- 无命中时只返回通用提示，不再建议「传 tier=all 查看候选」。

### 2.3 MCP 创建者边界

- 创建：`create_candidate` 写节点时记录 `actor=mcp:<grant_id>`、`reason=create`（PG 修订历史），并沿用已有 `source` 中 `type=manual, ref=mcp:<grant_id>` 的调用者标记（文件存储用它判定创建者）。
- 创建者判定：PG 取 `kb_node_revisions` 中该节点最早一条修订的 `actor`；文件存储（仅测试夹具与迁移工具）取节点 `source` 中的 `mcp:<grant_id>` 标记。没有创建者记录（如 worker/迁移节点）视为不可归属。
- 更新与废弃：目标必须存在、在授权范围内、且创建者等于调用方，否则 `409/1010`、`data.reason=not_owner`，节点不改。
- `deprecated` 节点对 MCP 不可再变：更新或重复废弃返回 `409/1010`、`data.reason=deprecated_immutable`。
- 乐观并发（`expected_revision`）与更新字段范围不变。
- 正文哈希去重与 slug 冲突的比对集合从「同项目 candidate」改为「同项目非 `deprecated` 节点」；`slug_conflict_candidate` 只适用于历史存量 `candidate` 行。

### 2.4 存量迁移

Alembic `0003` 在 `upgrade head` 时执行一次性数据迁移：

1. `kb_nodes.tier='candidate'` 的行改为 `canonical`，并生成新的 `revision`（16 位小写 hex）。
2. 每行向 `kb_node_revisions` 追加一条修订：`tier='canonical'`、`actor='system'`、`reason='ADR-0014'`，`before` 为迁移前的完整节点快照（`tier='candidate'`），`after` 为迁移后的完整快照。
3. 同一次迁移把 `kb_nodes.tier` 的列默认值从 `candidate` 改为 `canonical`。
4. `downgrade` 恢复 `tier='candidate'` 与迁移前的 `revision`，并删除 `reason='ADR-0014'` 的修订行。

迁移幂等：没有 `candidate` 行时不写任何修订，可重复执行。

## 3. 契约与文档同步

- `docs/contracts/node-schema.md` §5、`mcp-tools.md` §1、`architecture.md`、`kb-admin-api.md`、`contracts/README.md` 已同步。
- ADR-0006 第 23 行、ADR-0011、ADR-0012、ADR-0013 §7 标注被 ADR-0014 修订。
- `docs/CHANGELOG.md` 追加本条行为变更。
- `docs/plans/README.md` 登记本规格。

## 4. 验收条件

以下每条对应可执行测试；先制造 RED，再实现。

### 4.1 写入层级

1. worker 合并创建的新节点 `tier=canonical`；对同一 slug 再次抽取走追加合并（`updated` 非空），不再出现「跳过 canonical」。
2. MCP `kb_write_candidate` 返回 `tier=canonical`，落库节点为 `canonical`，`source` 包含 `mcp:<grant_id>`；PG 修订历史最早一条 `actor=mcp:<grant_id>`。
3. 管理台新建不传 `tier` 时为 `canonical`；显式传 `candidate` 返回 `422/1012`；更新显式传 `candidate` 同样 `422/1012`。

### 4.2 检索

4. 默认检索返回 `canonical` 节点，`deprecated` 不出现；`tier="all"` 时 `deprecated` 出现。
5. `tier="candidate"` 抛 `QueryError`；MCP `kb_search` 收到该值按参数错误拒绝。
6. 无命中提示不再包含「候选」字样。

### 4.3 创建者边界

7. 创建者更新自己创建的（已 canonical）节点成功，返回当前 `tier`；修订号递增。
8. 另一个 grant 更新或废弃该节点返回 `409/1010`、`not_owner`，节点内容不变。
9. 没有创建者记录的节点（直接写入、worker 或迁移节点）被更新/废弃返回 `not_owner`。
10. 创建者更新已 `deprecated` 的节点、或重复废弃，返回 `409/1010`、`deprecated_immutable`。
11. 同项目非 `deprecated` 节点正文哈希重复时创建返回 `content_duplicate`；历史 `candidate` 行仍返回 `slug_conflict_candidate`。

### 4.4 迁移

12. 在 `0002` 版本插入 `candidate` 节点后执行 `upgrade head`：该行变为 `canonical`、`revision` 变化，且新增一条 `actor='system'`、`reason='ADR-0014'` 的修订（`before.tier='candidate'`、`after.tier='canonical'`）。
13. 无 `candidate` 行时升级不新增修订，重复执行幂等。
14. `upgrade head` 后 `compare_metadata` 与 `Base.metadata` 零差异（列默认值同步）。

### 4.5 前端

15. `pnpm build` 通过；节点详情的层级下拉只有「有效 / 已废弃」，默认「有效」。
