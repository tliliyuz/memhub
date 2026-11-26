# ADR-0013 PostgreSQL 作为知识唯一真源

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-24 |
| 关联 | 取代 ADR-0002；部分取代 ADR-0004 §2（「运行态 ≠ 知识」边界）与 §3（dev 内存实现）；部分取代 ADR-0005 决策 4（不引 Alembic）与「kb-api 不访问数据库」的前提 |

## 背景

ADR-0002 把每条知识存成一个 markdown 文件、由 git 做版本化。当时否决「以 PostgreSQL 为真源」的理由是「个人知识库规模用不上」，前提是「最小改动即可满足」；实践后该前提被推翻：

- 真正的写入边界不是「一个文件」，而是「文件系统 + 目录约定 + `.kbs.json` 登记 + 写锁 + git」。这套约定在运行时不断分叉：目录存在不等于可写，登记表会漏项，写锁用跨进程文件锁，git 版本化依赖运行环境里恰好有 `.git`（生产未核实）。任何一项失配都会让「看起来在跑」与「实际没落盘」共存。
- 检索目前是全量扫 markdown 现算的子串打分，`matched` 返回写死的 `"fts"`，契约里承诺的 `kg.json` / 向量 / `fts.db` 三项投影有两项从未实现。规模到数百节点后，每次搜索都要读全部文件。
- 生产已有多项运行态在 PostgreSQL（ADR-0004），再让知识单独走文件，等于在同一系统里维护两套持久化、两套备份、两套一致性模型。
- 负责人在 2026-11-24 明确表态：当初走「文件即真源」是方案评审没细看，「最小改动」的前提应是高可用、高性能、高扩展，而不是省事。据此裁决：知识真源迁到 PostgreSQL，服务器上的 markdown 只作为一次性迁移源，迁移后删除。

本条的决策以负责人 2026-11-24 的裁决为准；随后由其确认了分区、检索、连接方式与交付边界四项具体选择（见决策各条）。

## 决策

1. **唯一真源是 PostgreSQL**。节点、边、知识库登记、候选/废弃治理状态、审计与节点修订历史全部进库；markdown 不再是真源，迁移后从服务器删除，仓库里只保留极少量测试 fixtures。原 ADR-0002 的「markdown 为真源、投影可重建」整条被本条取代。
2. **表结构（概要）**：
   - `kb_projects`：知识库登记（`id`、显示名、描述、`created_at`、`archived_at`）。原 `.kbs.json` 的语义迁移到此，「目录存在 ≠ 可写」改由登记行 + 状态列表达。
   - `kb_nodes`：节点（`id` 主键、`project`、`kind`、`entity_kind`、`title`、`tier`、`confidence`、`tags`、`body`、`source`、`valid_from/valid_until`、`supersedes`、`superseded_by`、`deprecated_reason`、`occurred_at/decided_at`、`status`、`created_at`、`updated_at`、`archived_at`、`revision`）。
   - `kb_edges`：边（`project`、`source`、`predicate`、`target`、`source_doc`，唯一约束 `(source, predicate, target)`）。
   - `kb_node_revisions`：节点每次写入的不可变历史（`node_id`、`revision`、`tier`、`actor`、`reason`、`before`、`after`、`created_at`），承载 ADR-0002 里由 git 提供的「可回滚、可审计」。`before/after` 存**含正文的完整节点快照**（已裁决），保证单节点可精确回滚。本轮建表并写入，但**不**实现审批型转正流程（见第 7 条）。
   - `kb_archives`：整库归档快照与状态（`archive_id`、`project`、`status`、`snapshot`（`bytea`，已裁决入库）、计数、`created_at`）。原 `_kb_archives/<id>/` 与 `blocked/` 标记迁移到此。
   - `kb_write_audit`：写入审计日志（`actor`、`project`、`node_id`、`action`、`result`、`created_at`），承接 ADR-0011 的 MCP 写审计与 ingest 的采集写审计。**与** `GET /api/v1/kb/audit` 的治理问题清单是两回事：后者（contradiction/orphan/stale 等）继续**现算、不入库**，只是数据源从文件换成表。
   - `kb_projects.revision` 与 `kb_nodes.revision`：乐观锁令牌，替代原文件 sha256 前 16 位的 `node_revision`。**格式不变：16 位小写十六进制**（`^[0-9a-f]{16}$`，契约与 MCP 输入硬校验此格式），由每次写入重新生成。契约「同一内容重写也产生新 revision」的语义保留：每次写入都生成新值。
3. **删除是软删 + 归档**：原 `_trash/` 与 `_kb_archives/` 的语义用 `archived_at`、`kb_archives` 表与归档快照表达；「永不硬删」原则保留。
4. **迁移工具用 Alembic**（负责人选定）。理由：知识表是本系统第一组会长期演进、需要按序应用与回滚追踪的结构化 schema，手工 `MIGRATIONS` 列表已不足以表达带索引、外键、数据回填的多步迁移。落地约束：
   - 新建 `alembic/` 与 `alembic.ini`，`target_metadata` 用 ORM `Base.metadata`。
   - **DSN 分角色，不复用 `MEMHUB_DB_URL`**：`MEMHUB_DB_URL` 是 `memhub_app`（ingest/worker，可碰运行态表与令牌摘要），kb 运行时与迁移都不得用它，否则违反第 6 条的受限边界。因此：
     - `MEMHUB_KB_DB_URL`：kb-api 运行时角色，只对 `kb_*` 做 DML。
     - `MEMHUB_KB_MIGRATE_DB_URL`：Alembic 迁移角色，对 `kb_*` 有 DDL（建表/索引）。迁移**带外执行**（`memhub migrate-kb` 或部署步骤），不在 kb 容器启动时跑——多副本容器各自跑迁移会竞争。迁移角色不读运行态表。
     - 若负责人在评审时选择「少一个键」，退路是让 kb 运行时角色同时拥有 `kb_*` 表所有权：仍碰不到运行态表，但公网可达的 kb 进程将持有 DDL 权，安全性弱于双角色；需负责人确认后采用。
   - 迁移体只用 Alembic `op.create_table` / `op.add_column` 等 Core 构造，不写裸 SQL。**注意门禁现状**：`scripts/check_no_raw_sql.py` 与 `check_async_io.py` 目前只扫 `src/`，不覆盖 `alembic/`；因此 ADR-0005 的「不写裸 SQL」在 alembic 目录内靠评审而非脚本把关，扩展扫描根已列为独立事项（见后果）。
   - 现有 5 张运行态表仍由 `ingest/migrations.py` 的冻结基线负责；本轮不搬动它们。Alembic 的基线修订只建 `kb_*` 表，并对已有库以 `alembic stamp` 衔接。**两套迁移共存**：同一 database 里存在 `schema_migrations`（运行态）与 `alembic_version`（知识表）两张版本表，各自独立、互不知晓；启动与部署必须分别执行两者（ingest 迁移在 ingest 启动时跑，Alembic 由 `memhub migrate-kb` / 部署步骤跑），任一未跑完都不算该库就绪。运行态表并入 Alembic 另立事项。
   - **分发包**：kb 容器需同时具备 `sqlalchemy`、`psycopg` 与 `alembic`，三者须加入 kb 的 wheelhouse 并重生成 `SHA256SUMS`（离线 `--network=none` 构建）；`alembic` 也从可选依赖转为基础/部署依赖，键集与打包清单同步。
5. **检索用应用层 BM25**（负责人选定「直接引 BM25，后期接向量做混合」）。实现方式：SQL 侧按授权范围、库、`kind`、`tier` 过滤出候选集，应用层用 BM25Okapi 打分排序；中文按字符二元组切分，**照搬现 `query._terms` 的规则**（空格切分 + 小写；CJK 连续字符 ≥4 个才补相邻二元组，只对 CJK 段补），不依赖分词器、不新增第三方依赖。**不**引入 ParadeDB / pg_search（需重启生产 PG）或 PG 内置 `ts_rank`（simple 配置对中文不分词）。分数对外仍归一化到 0–1（保持契约与前端口径），排序依据为 BM25 原始相关度。`matched` 从写死的 `"fts"` 改为如实的 `"bm25"`；**两处共建实现都要改**——MCP `kb_search` 与 kb-admin `GET /api/v1/kb/search` 共用 `query.py`，契约两份同时修订。向量混合检索按 ADR-0007 草案另案推进，不在本轮。
6. **kb-api 直连 PostgreSQL，使用专用受限角色**（负责人选定）。该角色只能读写 `kb_*` 表，不得访问运行态表（`devices`、`sources`、`batches`、`seen_shas`、`file_cursors`）与令牌摘要。据此部分取代 ADR-0007 草案里「kb 是否连库」的待决项为「直连 + 受限角色」。凭据经 `.env` 注入，键名见环境文档。kb 容器需新增 `sqlalchemy`/`psycopg` 依赖并重出 wheelhouse。
   - **落库位置**（2026-11-24 负责人裁决）：`kb_*` 表与运行态表**同库**，即生产 `memhub_prod`，不另建 database；备份仍是同一个 `pg_dump` 对象。由此带出一条必须在部署时落实的权限约束：PG 15+ 的 `public` schema 默认对 `PUBLIC` 有 `USAGE`，运行态 5 表就在 `public` 里（ADR-0004），仅靠「另建角色」无法自动挡住它。因此 `kb_*` 与 `alembic_version` 放进**专用 schema `kb`**，运行时与迁移角色的 `search_path` 固定为该 schema，并只授予该 schema 的 `USAGE` 与 `kb_*` 的表权限；对 `public` 的访问由不授权来阻断。生产上的建 schema、建角色与授权是带外运维动作，需负责人授权后执行。
   - `MEMHUB_KB_DB_URL` / `MEMHUB_KB_MIGRATE_DB_URL` 因此都指向 `memhub_prod`，区别在角色；测试仍指向 `memhub_dev`。
   - **连接数预算需重算**：ADR-0004 §6 定死 memhub ≤7 连接（ingest 2+3、worker 1+1，实例 `max_connections=60`）。kb 直连新增池，加 dev/测试并发，须重新核定预算并写进部署清单；未核定前 kb 池上限按最小可行值（如 2+2）配置。
7. **本轮交付边界**：存储迁移 + 契约修订 + schema 预留。节点修订历史表建好并写入，但候选转正、`## Change Log`、tier 变更审批流等治理缺口另立里程碑，不在本轮实现。**上传批次清单是否入 `kb_batches` 明确不在本轮**：`uploads/<batch_id>.json` 与「按文件路径推导批次状态」保持不变，只把上传入口的库存在性校验从文件/`target_access` 改为查 `kb_projects`（登记且 `archived_at is null`）。
8. **边端点不加外键**：`kb_edges.source/target` 允许指向尚未存在或已归档的节点，保留原 `_edges.jsonl` 的悬空边语义（`unresolved_edges`），`source_doc` 保留。实现时不得顺手加外键，否则会静默丢弃悬空边。
9. **迁移执行是一次性运维动作**：读服务器 `knowledge/` → 写入 `kb_*` → 校验（**逐节点、逐边的内容哈希比对，仅比计数不够**）→ `pg_dump` 与 `knowledge/` 打包备份 → 删除 markdown。提供 `--dry-run` 与 `--verify-only`，校验不通过不删除。迁移**必须处理归档数据**：`_trash/` 与 `_kb_archives/` 的历史节点按 `archived_at` / `kb_archives` 迁入（或明确只备份不迁，二者择一并写死）；「目录存在但未在 `.kbs.json` 登记」的库（如仓库 memhub 库）按已登记库导入 `kb_projects`，不得静默跳过而丢归属。删除动作需负责人在服务器上执行或明确授权。
10. **本地开发与测试直接用云端 PostgreSQL**（负责人选定），不再用内存实现替身。**测试隔离用 schema-per-test**（2026-11-24 负责人终裁，取代此前「每用例独立 database」的初步选择）：每个用例 `CREATE SCHEMA test_<uuid>`、跑完 `DROP SCHEMA CASCADE`，与 `tests/contract/test_state_store.py` 既有模式一致。落地形态（已在生产实例建好并验证）：dev 库 `memhub_dev`（owner `memhub_dev_app`），角色 `memhub_dev_app` 为 LOGIN、无 SUPERUSER/CREATEDB/CREATEROLE、`CONNECTION LIMIT 8`；并行开发 lane 共用该库与该账号。不需要 CREATEDB 测试角色，不偏离 ADR-0004；不触碰 `memhub_prod` 的角色、ACL 与 pg_hba。连接预算：现有 rolconnlimit 合计 50 + 8 = 58 ≤ `max_connections=60`（扣超级用户预留 3 后实际可用 57），测试并发建议 `-n ≤ 4`。本里程碑的验收命令**必须要求 `MEMHUB_TEST_DB_URL` 存在**——未设置时 PG 用例 skip 不计为通过。

## 备选与否决理由

| 备选 | 结论 |
|:---|:---|
| 维持 markdown 真源，只补 `.kbs.json` 与 git（ADR-0002 原路） | 否决：负责人的前提是「高可用、高性能、高扩展」，文件系统 + 目录约定的运行时漂移正是要消除的对象 |
| 手工 `MIGRATIONS` 前向追加管理知识表（ADR-0005 决策 4） | 否决：知识表需索引、外键与数据回填，前向列表难以表达；负责人选定 Alembic |
| ParadeDB / pg_search 提供库内 BM25 | 否决：需给生产宿主 PG 加 apt 源、超级用户建扩展、改 `shared_preload_libraries` 并重启，运维成本远高于收益 |
| PG 内置 `to_tsvector` / `ts_rank` 冒充 BM25 | 否决：simple 配置对中文不分词，召回明显回退；且并非 BM25 |
| kb 经 worker 内部接口代理访问向量/知识 | 否决（本轮）：worker 无监听面，加鉴权、限流、超时是新的一整块工程；直连 + 受限角色攻击面可控 |
| kb 复用 `memhub_app` 可写角色 | 否决：公网可达的 kb 进程会拿到运行态表与令牌摘要的访问权，权限过大 |
| 本轮同时补齐候选转正与审批流 | 否决（本轮）：把存储迁移与治理闭环绑在一次评审里，变更面与风险都过大 |

## 后果

- ADR-0002 全文被取代；其「写知识 = 写文件 + git commit」由 `kb_node_revisions` + `pg_dump` 备份承接。ADR-0004 §2「知识真源仍是 markdown」与 §3「dev 用 MemoryStore」失效，运行态部分结论继续有效。ADR-0005 决策 4 的「不引 Alembic」本轮被改；`kb-api 不访问数据库` 的前提失效。
- `docs/architecture.md` 数据流、`docs/contracts/node-schema.md`（真源形态与投影表）、`docs/contracts/kb-admin-api.md`、`docs/contracts/mcp-tools.md`（`matched` 语义）、`docs/tech/ENVIRONMENT.md`（新增 kb 直连键、测试键）必须同步修订。**投影与 explorer 的去留**：ADR-0002 被取代后，`kg.json` / `vector/` / `fts.db` 三项投影中两项从未实现，且 kb 不再读 markdown，投影与 semantica explorer 失去意义；`MEMHUB_KB_GRAPH`、`MEMHUB_KB_GRAPH_PORT`、`MEMHUB_KB_AUTO_REBUILD` 三项键可能整体作废。本轮先在契约中标注待删，实现时与 `projection.py`、semantica 依赖一并处置，删除与否由负责人确认。**2026-11-25 更新**：负责人确认删除；`projection.py`、`kg.json`/`rebuild` 接口、`memhub project` / `serve` 命令与 explorer 服务已移除，`MEMHUB_KB_GRAPH` / `MEMHUB_KB_GRAPH_PORT` / `MEMHUB_KB_AUTO_REBUILD` 三项键作废，执行结果见 [CHANGELOG](../CHANGELOG.md)。
- 新增运维面：kb 专用角色及其授权、Alembic 迁移执行（新增 `alembic` 依赖与 wheelhouse）、一次性数据迁移与删除、cloud PG 作为 dev/测试依赖、连接数预算重算。
- **门禁覆盖缺口**：`check_no_raw_sql.py` / `check_async_io.py` 只扫 `src/`，`alembic/` 不在扫描范围。需把 `alembic/` 加入两脚本扫描根（作为独立提交，附带门禁自测），否则「不写裸 SQL」在迁移目录内无脚本把关。
- 备份与恢复：`pg_dump -Fc` 成为唯一全量备份手段；恢复演练在装有 PG 的云主机做。迁移后失去「直接读文件即可审阅」的能力，人工审阅改走管理台与库查询。
- git 不再承载知识历史；服务器 `knowledge/` 删除后，回滚点只有数据库备份。因此删除前的 `pg_dump` + `knowledge/` 打包备份是硬前置。
- 检索行为从子串打分变为 BM25 排序，结果顺序会变化；`matched` 标签改为 `bm25`，调用方若按 `"fts"` 判断需同步修改（契约中此前已注明该字段不是索引或向量召回）。
