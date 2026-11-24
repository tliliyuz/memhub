# 知识真源迁到 PostgreSQL：实施规格

| 属性 | 值 |
|:---|:---|
| 文档状态 | draft（待负责人评审） |
| 最后更新 | 2026-11-24 |
| 适用范围 | 知识真源的 PG 数据模型、存储边界、一次性迁移、检索与并发语义、验收条件与待裁决项 |
| 不负责 | 架构裁决（见 [ADR-0013](../decisions/ADR-0013-postgres-source-of-truth.md)）、对外字段取值（见 [contracts](../contracts/README.md)）、实施历史（见 [CHANGELOG](../CHANGELOG.md)） |

## 1. 目标与范围

承接 [ADR-0013](../decisions/ADR-0013-postgres-source-of-truth.md)：把知识真源从 `knowledge/**/*.md` 迁到 PostgreSQL，markdown 只作一次性迁移源，迁移校验通过后从服务器删除。

### 1.1 本轮范围

- 知识表与节点修订历史表的设计（schema 预留）。
- `kb_*` 存储层（异步 SQLAlchemy ORM）替换 `KnowledgeStore` 的文件读写。
- 检索改为应用层 BM25（`matched` 由 `"fts"` 改为 `"bm25"`）。
- 一次性迁移工具（markdown → PG）与校验。
- 契约与环境文档同步。

### 1.2 不在本轮

- 向量检索与混合排序（另行按 ADR-0007 推进）。
- 候选转正、tier 变更审批流、`## Change Log` 的治理流程（本轮只建修订历史表并在写入时落历史）。
- 运行态表（`devices` 等）并入 Alembic。
- 生产部署与线上数据删除（运维动作，需负责人授权）。

## 2. 存储边界

| 数据 | 今天 | 迁移后 |
|:---|:---|:---|
| 节点正文与元数据 | `knowledge/<project>/<kind>/<slug>.md` | `kb_nodes` |
| 边 | `<project>/_edges.jsonl` | `kb_edges` |
| 知识库登记 | `.kbs.json` | `kb_projects` |
| 归档快照 | `_kb_archives/<id>/snapshot.zip` + `blocked/` 标记 | `kb_archives`（快照字节存 bytea 或对象存储，见 §9 待裁决） |
| 回收站 | `_trash/<stamp>/<id>.md` + `.meta.json` | `kb_nodes.archived_at` + `kb_node_revisions` 快照 |
| 修订/回滚 | git 提交 | `kb_node_revisions` + `pg_dump` 备份 |
| 原始增量 | `raw_store/`（不变） | `raw_store/`（不变） |
| 上传批次清单 | `uploads/<batch_id>.json`（不变，或入 `kb_batches`，见 §9） | 见 §9 |
| 运行态 | `devices` 等 5 表（不变） | 不变 |

`docs/architecture.md` 的边界口径随之更新：pg 存知识真源 + 运行态；文件系统只剩 `raw_store/`、`uploads/`、`processed_raw/`、`knowledge/`（迁移后删除）。

## 3. 数据模型

字段类型为 PG 16。所有时间 `timestamptz`，一律 UTC。`revision` 是乐观锁令牌，16 位小写十六进制字符串，语义与契约 `expected_revision` 不变。

### 3.1 `kb_projects`（知识库登记）

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | text PK | 匹配 `KB_ID_RE`，不可改 |
| `name` | text not null | 显示名，空则回落 `id` |
| `description` | text not null default `''` | |
| `revision` | text not null | 元数据乐观锁 |
| `created_at` / `updated_at` | timestamptz not null | |
| `archived_at` | timestamptz null | 非空即整库归档，等价原 `blocked/<id>` 标记 |

约束：`id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'`。不再需要「目录存在」这一层；「已登记且活动」= 存在行且 `archived_at is null`。

### 3.2 `kb_nodes`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | text PK | `<project>/<kind>/<slug>`，等于原文件相对路径去扩展名 |
| `project` | text not null references `kb_projects(id)` | 首段 |
| `kind` | text not null | `Kind` 枚举 |
| `entity_kind` | text null | `kind=entity` 时必填（应用层校验） |
| `title` | text not null | 2–200 字符 |
| `tier` | text not null default `'candidate'` | `candidate/canonical/deprecated` |
| `confidence` | double precision null | 0–1 |
| `tags` | text[] not null default `'{}'` | |
| `body` | text not null | 原 markdown 正文（不含 frontmatter） |
| `source` | jsonb not null default `'[]'` | `SourceRef[]` |
| `valid_from` / `valid_until` | timestamptz null | |
| `superseded_by` | text null | |
| `deprecated_reason` | text null | |
| `occurred_at` / `decided_at` | timestamptz null | |
| `status` | text null | `question` 的 open/resolved |
| `created_at` / `updated_at` | timestamptz not null | |
| `archived_at` | timestamptz null | 非空即软删（原 `_trash`） |
| `revision` | text not null | 每次写入重算 |

索引：`(project) where archived_at is null`、`(project, kind)`、`(tier)`。全表量级预计数百到数千行，不建倒排。

### 3.3 `kb_edges`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | bigserial PK | |
| `project` | text not null | 边文件归属（原 `_edges.jsonl` 所在库） |
| `source` / `target` | text not null | 完整 id 或短别名，语义同原 `_resolve` |
| `predicate` | text not null | `Predicate` 枚举 |
| `source_doc` | text null | |
| `created_at` | timestamptz not null | |

唯一约束：`(source, predicate, target)`（与原 `append_edges` 去重键一致）。短别名解析仍在应用层按「完整 id 优先、库内唯一 slug 兜底」实现，行为不变。

### 3.4 `kb_node_revisions`（预留）

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | bigserial PK | |
| `node_id` | text not null | 不设 FK，节点软删后历史仍保留 |
| `revision` | text not null | 写入后的新 revision |
| `tier` | text not null | 写入后的 tier |
| `actor` | text null | 调用者（`ui:<user>` / `mcp:<grant>` / worker） |
| `reason` | text null | |
| `before` / `after` | jsonb not null | 节点快照（不含正文时可只存元数据，见 §9） |
| `created_at` | timestamptz not null | |

本轮：每次 `kb_nodes` 写入在同一事务内追加一条；不提供审批动作。

## 4. 迁移（Alembic）

- `alembic/versions/0001_kb_tables.py` 建上述四表与索引；只用 `op.create_table` / `op.create_index`，不写 SQL 字符串（`scripts/check_no_raw_sql.py` 不放宽）。
- `alembic/env.py` 从 `MEMHUB_DB_URL` 取 DSN、`target_metadata` 用 ORM `Base.metadata`。
- 与既有 `ingest/migrations.py` 冻结基线并存：运行态表不动；对已建 `schema_migrations` 的库以 `alembic stamp` 衔接，避免两套 DDL 描述同一表。运行态表迁入 Alembic 另立事项。
- 回滚：知识表只有 `upgrade` 加表，`downgrade` 为 `drop_table`（仅空库演练用；生产回滚以 `pg_dump` 恢复为准）。

## 5. 一次性迁移工具

`memhub migrate-kb --knowledge-dir <dir> [--dsn <url>] [--dry-run] [--verify-only] [--delete-source]`

1. 只读扫描 `knowledge/`：`*.md`（跳过 `_trash`、`_kb_archives`）、每个 `<project>/_edges.jsonl`、`.kbs.json`。
2. frontmatter → `NodeFrontmatter`；正文 → `body`；`.kbs.json` → `kb_projects`；边行 → `kb_edges`。
3. `--dry-run`：只解析与统计，不写库、不删文件。
4. 写入用单事务（或分批事务 + 幂等 upsert）；失败整体回滚。
5. `--verify-only`：库中 `count(kb_nodes where archived_at is null)`、各库节点数、边数、每库 `_edges.jsonl` 行数，与磁盘逐一比对，输出差异；不一致非 0 退出。
6. `--delete-source`：**仅在** `--verify-only` 通过且负责人已授权时才可执行；先 `pg_dump` 与 `knowledge/` 打包备份，再删除。默认不删。
7. 幂等：重复运行以 `id` upsert，不产生重复节点。

## 6. 检索（应用层 BM25）

- `kb_search`：SQL 侧过滤 `archived_at is null`、项目授权范围、`kind`、`tier`；取候选集后应用层 BM25Okapi 排序，返回 `limit` 条。
- 分词：复用 `query._terms` 的规则（空白切分、小写；≥4 个 CJK 字的 token 额外产出相邻二元组），作为 BM25 的文档/查询 token。不引入分词器依赖。
- 结果仍返回 `id/kind/tier/title/score/snippet/updated_at/matched`；`matched` 改为 `"bm25"`。`score` 归一化口径可与现状不同，但必须单调于 BM25 相关度。
- `kb_related` / `kb_audit_list` / `kb_read` 不变，只是数据源从文件换成表。

## 7. 并发、写锁与 revision

- 跨进程文件锁（`.memhub-write-v2.lock`）语义由 PG 事务替代：一次写操作 = 一个事务；并发更新用 `SELECT ... FOR UPDATE` 或 `revision` 比较（乐观锁）。`expected_revision` 与现状一致。
- `WriteDeferred(reason=busy/pending)`：`busy` 改为 PG 锁等待超时；`pending`（归档事务未完成）由 `kb_archives` 的状态列表达。
- `node_revision`：不再取文件 sha256，改为 `kb_nodes.revision`（写入时生成 16 位 hex）。契约字段名与长度不变。
- 归档/恢复的状态机（原 `archive.py` 的 `pending.json` + 回滚日志）用 `kb_archives.status` + 事务整体回滚替代；「永不硬删」由软删列 + 快照保证。

## 8. 验收条件（SDD：由本规格导出，先 RED 后 GREEN）

1. 迁移：对固定 fixture 目录（合成节点/边/登记）跑迁移，`--verify-only` 通过；再跑一次幂等，计数不变。
2. 节点往返：建库 → 写候选 → `kb_read` → 改 → 读回，字段与 body 完全一致（含中文与多行）。
3. 乐观锁：用旧 `revision` 更新返回 `409/1010 revision_conflict`，数据不变。
4. tier 边界：`kb_update_candidate`/`kb_deprecate` 命中 canonical 返回 `not_candidate`。
5. 去重与拒绝码：slug 冲突、正文哈希去重、证据校验、每日上限的 `data.reason` 与原实现一致。
6. 检索：给定固定语料与查询，BM25 排序确定且可复现；`matched == "bm25"`；`tier` 过滤与空结果 `hint` 不变。
7. 归档/软删：整库归档后节点从检索消失、可恢复；恢复后计数一致。
8. 上传：`/api/v1/kb/uploads` 目标校验改查 `kb_projects`，未登记/已归档仍 `404/422`。
9. 门禁：`check_no_raw_sql.py`、`check_async_io.py`、`mypy`、文档格式与 ADR 治理全绿。

## 9. 待裁决项

1. **kb_archives 快照存放**：整库归档快照是 bytea 入库，还是继续放文件系统 + 库只存元数据？入库更统一但大对象增加备份体积；文件保留则真源仍有一处文件依赖。
2. **上传批次清单**：`uploads/<batch_id>.json` 是否并入 `kb_batches` 表（决策 2 的「批次入库」），还是保持文件、仅把库存在性改查 `kb_projects`。
3. **`kb_node_revisions` 是否存正文快照**：存全量 `before/after` 体积大但可精确回滚；只存元数据则回滚需结合备份。
4. **受限角色授权范围**：`kb_*` 全部 DML，是否需要单独的只读角色给 `/mcp` 读工具与读写角色分离。
5. **dev/测试隔离**：每用例独立 schema（倾向）还是独立 database；cloud PG 的连接配额是否够测试并发。

## 10. 契约与文档同步清单

- `docs/architecture.md`：数据流、组件职责（worker 写库而非写 md）、`knowledge/` 的去留、部署形态。
- `docs/contracts/node-schema.md`：§1 真源形态改为表；§6 投影表（`kg.json`/`vector/`/`fts.db`）改为「表 + BM25 + 未来向量」。
- `docs/contracts/kb-admin-api.md`：§4.8 投影语义、§5 不变式（去掉 git/`_trash` 文件口径）。
- `docs/contracts/mcp-tools.md`：`matched` 语义（`fts`→`bm25`）、「以 Markdown 为真源」改为库、revision 来源。
- `docs/tech/ENVIRONMENT.md`：kb 直连 DSN 键（复用 `MEMHUB_DB_URL` 还是新增 `MEMHUB_KB_DB_URL`）、受限角色说明、测试 `MEMHUB_TEST_DB_URL`。
- `docs/guides/DEVELOPMENT.md`：验证矩阵与端到端命令（§9 的 markdown 闭环改为库）。
- `docs/CHANGELOG.md`：实现落地后按日期追加。
