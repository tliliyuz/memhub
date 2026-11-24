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
| 写入审计 | ingest `_audit` 日志 + MCP 审计（文件/日志） | `kb_write_audit` 表 |
| 原始增量 | `raw_store/`（不变） | `raw_store/`（不变） |
| 上传批次清单 | `uploads/<batch_id>.json`（不变） | **不变**（本轮不入 `kb_batches`，见 §9） |
| 运行态 | `devices` 等 5 表（不变） | 不变 |

`docs/architecture.md` 的边界口径随之更新：pg 存知识真源 + 运行态；文件系统只剩 `raw_store/`、`uploads/`、`processed_raw/`、`knowledge/`（迁移后删除）。

治理问题清单（`GET /api/v1/kb/audit` 的 contradiction/orphan/stale 等）**继续现算、不入库**，只是数据源从文件换成表，与本表的「写入审计」是两回事，不要合并。

## 3. 数据模型

字段类型为 PG 16。所有时间 `timestamptz`，一律 UTC。`revision` 是乐观锁令牌，**16 位小写十六进制字符串**（`^[0-9a-f]{16}$`，契约与 MCP 输入硬校验），每次写入重新生成；语义沿用契约 §3「同一内容重写也产生新 revision」。

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
| `revision` | text not null | 每次写入重算，16 位 hex |

索引：`(project) where archived_at is null`、`(project, kind)`、`(tier)`。全表量级预计数百到数千行，不建倒排。

归档与恢复：`_trash/` 的软删节点用 `archived_at` + `kb_node_revisions` 快照表达；整库归档用 `kb_archives`（§3.5）与 `kb_projects.archived_at` 表达。

### 3.3 `kb_edges`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | bigserial PK | |
| `project` | text not null | 边文件归属（原 `_edges.jsonl` 所在库） |
| `source` / `target` | text not null | 完整 id 或短别名，语义同原 `_resolve` |
| `predicate` | text not null | `Predicate` 枚举 |
| `source_doc` | text null | |
| `created_at` | timestamptz not null | |

唯一约束：`(source, predicate, target)`（与原 `append_edges` 去重键一致）。**端点 `source`/`target` 不加外键**：允许指向尚不存在或已归档的节点，保留原 `_edges.jsonl` 的悬空边语义（`unresolved_edges`），`source_doc` 保留。短别名解析仍在应用层按「完整 id 优先、库内唯一 slug 兜底」实现，行为不变。

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

### 3.5 `kb_archives`（整库归档）

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `archive_id` | text PK（32 位 hex） | |
| `project` | text not null | 被归档库 |
| `status` | text not null | `pending` / `active` / `restoring` |
| `snapshot` | bytea null | 归档快照（若选择入库，见 §9 待裁决） |
| `archived_count` / `removed_edges` | integer not null | |
| `actor` / `deleted_at` | text / timestamptz | |
| `created_at` | timestamptz not null | |

原 `_kb_archives/<id>/active.json` 与 `blocked/<project>` 标记的语义映射到此表：`status=pending` 等价未完成事务（阻断普通写入），`project` 已归档由 `kb_projects.archived_at` 表达。

### 3.6 `kb_write_audit`（写入审计）

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | bigserial PK | |
| `actor` | text null | `ui:<user>` / `mcp:<grant>` / worker |
| `project` / `node_id` | text null | |
| `action` | text not null | `create` / `update` / `deprecate` / `delete` / `restore` / `ingest` |
| `result` | text not null | `ok` / 拒绝原因码 |
| `created_at` | timestamptz not null | |

不含正文与 token。与 `GET /api/v1/kb/audit`（治理问题清单，现算不入库）分开。

## 4. 迁移（Alembic）

- `alembic/versions/0001_kb_tables.py` 建 §3 的表与索引（`kb_projects`、`kb_nodes`、`kb_edges`、`kb_node_revisions`、`kb_archives`、`kb_write_audit`）；只用 `op.create_table` / `op.create_index`，不写 SQL 字符串。
- `alembic/env.py` 从 `MEMHUB_KB_DB_URL`（受限角色，与 `MEMHUB_DB_URL` 分开，见 §10）取 DSN、`target_metadata` 用 ORM `Base.metadata`。
- **门禁覆盖**：`check_no_raw_sql.py` / `check_async_io.py` 目前只扫 `src/`，不覆盖 `alembic/`；须把 `alembic/` 加入两脚本扫描根并补自测，否则迁移目录无脚本把关。
- **两套迁移共存**：同一 database 里 `schema_migrations`（运行态，`ingest/migrations.py`）与 `alembic_version`（知识表）各自独立。部署与启动须分别执行：ingest 迁移随 ingest 启动，Alembic 由 `memhub migrate-kb` 或部署步骤跑；任一未跑完，该库不算就绪。运行态表并入 Alembic 另立事项。
- 回滚：知识表只有 `upgrade` 加表，`downgrade` 为 `drop_table`（仅空库演练用；生产回滚以 `pg_dump` 恢复为准）。

## 5. 一次性迁移工具

`memhub migrate-kb --knowledge-dir <dir> [--dsn <url>] [--dry-run] [--verify-only] [--delete-source]`

1. 只读扫描 `knowledge/`：`*.md`（跳过 `_trash`、`_kb_archives`，归档数据单独处理见第 3 步后）、每个 `<project>/_edges.jsonl`、`.kbs.json`。
2. frontmatter → `NodeFrontmatter`；正文 → `body`；`.kbs.json` → `kb_projects`；边行 → `kb_edges`。
3. **归档数据**：`_trash/<stamp>/<id>.md` 与 `_kb_archives/*` 内的历史节点按 `archived_at` / `kb_archives` 迁入；迁移脚本必须有显式开关（迁或只备份不迁），默认 `--dry-run` 时两者都只统计不写。
4. **未登记库**：目录存在但不在 `.kbs.json` 的知识库（如仓库实测的 `memhub` 库）导入为 `kb_projects` 行（`name=id`、`description=''`），不得跳过而丢节点归属；遇 `.kbs.json` 与目录集合不一致时，`--verify-only` 列出差异。
5. `--dry-run`：只解析与统计，不写库、不删文件。
6. 写入用单事务（或分批事务 + 幂等 upsert）；失败整体回滚。
7. `--verify-only`：**逐节点、逐边比对内容哈希**，不止比对计数——`kb_nodes` 每行的 `sha256(title+body+稳定字段序列化)` 与磁盘文件同口径比对；各库节点数、边数、每库 `_edges.jsonl` 行数；输出差异，不一致非 0 退出。悬空边（端点不存在）必须原样迁入，不得因校验丢弃。
8. `--delete-source`：**仅在** `--verify-only` 通过且负责人已授权时才可执行；先 `pg_dump` 与 `knowledge/` 打包备份，再删除。默认不删。
9. 幂等：重复运行以 `id` upsert，不产生重复节点。

## 6. 检索（应用层 BM25）

- `kb_search`：SQL 侧过滤 `archived_at is null`、项目授权范围、`kind`、`tier`；取候选集后应用层 BM25Okapi 排序，返回 `limit` 条。
- 分词：照搬 `query._terms` 的规则（空白切分、小写；**CJK 连续字符 ≥4 个**才额外产出相邻二元组，只对 CJK 段补），作为 BM25 的文档/查询 token。阈值与条件必须原样保留，否则召回面会变。不引入分词器依赖。
- 结果仍返回 `id/kind/tier/title/score/snippet/updated_at/matched`；`matched` 改为 `"bm25"`。`score` 对外仍归一化到 0–1（契约与前端在用的口径），排序依据为 BM25 原始相关度；归一化公式须单调、稳定并在契约注明，与现 `raw/(raw+5)` 的具体形式可不同。
- `matched` 同时影响两处文档：MCP `kb_search`（`mcp-tools.md`）与 kb-admin `GET /api/v1/kb/search`（`kb-admin-api.md` §4.5），共用 `query.py`，必须一起改。
- `kb_related` / `kb_audit_list` / `kb_read` 不变，只是数据源从文件换成表。

## 7. 并发、写锁与 revision

- 跨进程文件锁（`.memhub-write-v2.lock`）语义由 PG 事务替代：一次写操作 = 一个事务；并发更新用 `SELECT ... FOR UPDATE` 或 `revision` 比较（乐观锁）。`expected_revision` 与现状一致。
- `WriteDeferred(reason=busy/pending)` 两个 reason 客户端在用，PG 版必须保留等价错误：`busy` 改为事务/锁等待超时；`pending`（归档事务未完成）由 `kb_archives.status=pending` 表达。
- `node_revision`：不再取文件 sha256，改为 `kb_nodes.revision`（每次写入生成 16 位 hex）。契约字段名与长度不变。
- 归档/恢复的状态机（原 `archive.py` 的 `pending.json` + journal 回滚）用 `kb_archives.status` + 事务整体回滚替代；若 DB 事务能完全覆盖「journal + 反向补偿」，就删掉文件版两套机制，否则显式说明保留部分。原 `_preflight`「删目录必须列出全部子项」的防误删约束，DB 版要有等价物（如删除前校验该库无未列节点）。「永不硬删」由软删列 + 快照保证。
- 迁移期两套真源并存时，文件锁需覆盖文件侧（归档快照打包仍是文件操作）。

## 8. 验收条件（SDD：由本规格导出，先 RED 后 GREEN）

1. 迁移：对固定 fixture 目录（合成节点/边/登记）跑迁移，`--verify-only` 通过；再跑一次幂等，计数不变；含一条未登记库与一条悬空边。
2. 节点往返：建库 → 写候选 → `kb_read` → 改 → 读回，字段与 body 完全一致（含中文与多行）。
3. 乐观锁：用旧 `revision` 更新返回 `409/1010 revision_conflict`，数据不变；`revision` 恒为 16 位 hex。
4. tier 边界：`kb_update_candidate`/`kb_deprecate` 命中 canonical 返回 `not_candidate`。
5. 去重与拒绝码：slug 冲突、正文哈希去重、证据校验、每日上限的 `data.reason` 与原实现一致；**`daily_limit_exceeded` 仍为 409/1010**（原实现是 `CandidateConflict`，不是 429）。
6. 检索：给定固定语料与查询，BM25 排序确定且可复现；`matched == "bm25"`；`score ∈ [0,1]`；`tier` 过滤与空结果 `hint` 不变。
7. 归档/软删：整库归档后节点从检索消失、可恢复；恢复后计数一致；归档期间普通写入返回 `busy/pending` 等价错误。
8. 上传：`/api/v1/kb/uploads` 目标校验改查 `kb_projects`，未登记/已归档仍 `404/422`；批次清单仍走文件。
9. 门禁：`check_no_raw_sql.py`、`check_async_io.py`（含 `alembic/` 覆盖）、`mypy`、文档格式与 ADR 治理全绿。
10. **验收命令必须要求 `MEMHUB_TEST_DB_URL` 存在**：未设置时 PG 用例 skip **不计为通过**，命令应显式失败或标注未验证。

## 9. 待裁决项

1. **kb_archives 快照存放**：整库归档快照是 `bytea` 入库，还是继续放文件系统、库只存元数据（`snapshot` 列存引用）？入库更统一但增加备份体积；留文件则真源仍有一处文件依赖。
2. **`kb_node_revisions` 是否存正文快照**：存全量 `before/after` 体积大但可精确回滚；只存元数据则回滚需结合备份。
3. **受限角色授权范围**：`kb_*` 全部 DML，是否需要单独的只读角色给 `/mcp` 读工具与读写角色分离。
4. **dev/测试隔离**：每用例独立 schema（倾向，与现有 `test_state_store` 临时 PG 一致）还是独立 database；cloud PG 的连接配额是否够测试并发。

已决（不再是待裁决）：上传批次清单本轮**不入** `kb_batches`（ADR-0013 §7）；边端点**不加**外键（§8）；连接数预算需重算（§6）。

## 10. 契约与文档同步清单

- `docs/architecture.md`：数据流、组件职责（worker 写库而非写 md）、`knowledge/` 的去留、部署形态。
- `docs/contracts/node-schema.md`：§1 真源形态改为表；§6 投影表（`kg.json`/`vector/`/`fts.db`）改为「表 + BM25 + 未来向量」。
- `docs/contracts/kb-admin-api.md`：§4.8 投影语义、§5 不变式（去掉 git/`_trash` 文件口径）。
- `docs/contracts/mcp-tools.md`：`matched` 语义（`fts`→`bm25`）、「以 Markdown 为真源」改为库、revision 来源。
- `docs/tech/ENVIRONMENT.md`：新增 kb 直连键 `MEMHUB_KB_DB_URL`（受限角色，与 `MEMHUB_DB_URL` 分开）、测试 `MEMHUB_TEST_DB_URL`、受限角色说明；标注 `MEMHUB_KB_GRAPH` / `MEMHUB_KB_GRAPH_PORT` / `MEMHUB_KB_AUTO_REBUILD` 三项投影相关键待删（见 §9 已决项与 ADR-0013 后果）。
- `docs/guides/DEVELOPMENT.md`：验证矩阵与端到端命令（§9 的 markdown 闭环改为库）。
- `docs/CHANGELOG.md`：实现落地后按日期追加。
