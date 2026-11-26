# CHANGELOG

## 2026-11-26（本地 Git 不问、验收后强制回 dev，资源占用约束）

- `docs(governance)`：`CLAUDE.md` / `AGENTS.md` §2 把分支闭环与 Git 授权改为强制约束：任务验收后必须立即把特性分支经 `--no-ff` 合回 `dev`、切回 `dev`，然后删除该分支与自己的 worktree，不得以等待排期或「已提交」为由滞留；本地 Git 操作一律直接执行，禁止征求或等待负责人确认，只有远端操作需要当次授权。新增资源占用约束：验收前查看本项目标签页与进程，只按需启动，禁止多开标签页与常驻 Node/Python 服务进程，验收后全部关闭；多开并发需先确认。ADR 检查：未命中（只约束执行方式，不涉及部署拓扑、契约或密钥边界）。验证：纯文档修订，无业务 RED；`check_document_format.py`、`check_agent_entrypoints_sync.py`、`check_adr_governance.py`、`check_document_ownership.py --changed` 与 `git diff --check` 均通过。

## 2026-11-26（测试入口自动读取 `.env` 的测试库 DSN）

- `test(conftest)`：新增 `tests/env_loader.py`，`tests/conftest.py` 导入时调用 `resolve_test_db_url()`——进程环境变量优先；未设置或为空时依次读仓库根 `.env` 与（worktree 场景）主 checkout 的 `.env`，只读 `MEMHUB_TEST_DB_URL` 一个键，不加载整份文件，避免覆盖 `MEMHUB_DB_URL`、`PG*` 等运行态变量；两处都拿不到时维持 skip。`pyproject.toml` 的 pytest 配置增加 `pythonpath = ["tests"]`。
- RED：先写 `tests/unit/test_env_loader.py`（11 条），`pytest -q tests/unit/test_env_loader.py` 得到 `ModuleNotFoundError: No module named 'env_loader'`（目标模块不存在）。
- GREEN：实现 `tests/env_loader.py` 并接入 conftest 后同命令 11 passed。中途发现一条用例把「主 checkout」硬编码为 `parents[2]`，在 worktree 中必然失败；改为在临时 git 仓库里验证，测试不再依赖运行位置。
- 端到端：在 worktree（无 `.env`）中不导出 `MEMHUB_TEST_DB_URL` 全量 `pytest`：556 passed / 1 skipped（skip 是未启动 MCP 服务器的无关用例，PG 用例实际执行；基线 545 条 + 新增 11 条）。
- 文档：`docs/tech/ENVIRONMENT.md` 的 `MEMHUB_TEST_DB_URL` 行写明解析顺序与失败语义；`docs/guides/DEVELOPMENT.md` 的 PG 契约测试命令改为写 `.env` 后直接 `pytest`。
- 静态检查：`ruff check src tests scripts alembic`、`ruff format --check src tests scripts alembic`、`python -m mypy src`（47 文件）均通过。

## 2026-11-26（第一性原理归因与信息沉淀）

- `docs(governance)`：`CLAUDE.md` / `AGENTS.md` 新增 §1.2「归因与信息沉淀」。归因要求先问「为什么会出现」，再判断方案能否从根本上解决问题、泛化性是否足够，不以一次性补丁交付；任何路径得到的长期信息先判断是否会被复用，长期事实必须在同一次变更里落进权威文档、SOP、配置键、脚本、测试或 `.env`，不得只解决当前会话后静默丢弃；无法落盘时须说明它仅在会话内及缺什么前置条件。§2 的 `.env.example` 键名同步规则是它的一个具体应用。ADR 检查：未命中（只约束工作方法，不涉及部署拓扑、契约或密钥边界）。验证：纯文档修订，无业务 RED；`check_document_format.py`、`check_agent_entrypoints_sync.py`、`check_adr_governance.py`、`check_document_ownership.py --changed` 与 `git diff --check` 均通过。

## 2026-11-26（MCP 调用轨迹：管理台页面）

- `feat(web)`：治理侧栏新增「调用轨迹」（`/traces`），展示调用总数、成功、失败、拒绝和按工具分布。明细按工具、状态、凭据和近 1/7/30 天筛选，支持分页。请求 ID 悬停显示全值；凭据无名称时显示摘要 ID，两者均缺失时显示 `unknown`。空态提示 30 天明细保留期。汇总接口失败时单独提示，不显示成「没有调用」。
- `docs`：规格 §7 表格补「请求 ID」列，§9.4 验收 15 的构建命令改为 `pnpm build`。
- `test`：新增 `web/tests/mcp-traces.test.mjs`（查询参数透传、汇总路径、503 错误码、凭据降级、时间范围换算）。RED：目标模块 `web/src/lib/traces.ts` 不存在，`node --test tests/mcp-traces.test.mjs` 报 `ERR_MODULE_NOT_FOUND`；GREEN 后与既有用例共 10 项通过。
- 验证（2026-11-26）：`node --test tests/mcp-traces.test.mjs tests/kb-project-archive.test.mjs` 10 passed；`pnpm build`（含 `tsc -b`）通过；ego-browser + 本地模拟查询接口验证治理入口、有数据与空态、分页、工具/状态/凭据/时间范围筛选与清除，验收标签页已关闭。未连接真实数据库做页面联调。
- ADR 检查：页面属于 [ADR-0014](decisions/ADR-0014-mcp-call-trace.md) 决策 6 的实现范围，未新增架构决策；ADR-0014 状态仍为 `proposed`，待负责人裁决为 accepted。

## 2026-11-25（MCP 调用轨迹：服务端落库与查询接口）

- `feat(mcp)`：`/mcp` 入口把每次 `tools/call`（成功、业务错误、未预期异常）与鉴权/路由拒绝（401/403/405/429）记入新表 `kb_mcp_trace`；`initialize`、`tools/list`、`ping`、通知与非 `/mcp` 路径不记录。只记元数据，参数原文不落库，仅留规范化 JSON 的 sha256。
- `feat(mcp)`：`Grant` 新增可选 `name`（strip 后 1–64 字符，禁控制字符），随 `Credential` 进入轨迹；旧配置无 `name` 照常启动，展示层按 `name || id || "unknown"` 降级。
- `feat(mcp)`：可靠落库——独立事务写入，失败退避重试 3 次（共 4 次尝试），仍失败追加到 JSONL spool（flush + fsync），下次成功写入前补投并以 `trace_id` 去重；spool 超 8 MiB 丢最旧行，重写走临时文件加原子替换。spool 也不可用时记 ERROR，这是唯一会丢记录的路径。记录失败不改变 `tools/call` 的返回与状态码。
- `feat(kb)`：明细保留 30 天，清理挂在写入路径上，按小时节流，失败只记 WARNING。
- `feat(kb-api)`：新增 `GET /api/v1/kb/mcp-traces`（分页与过滤）与 `/summary`（按状态、工具、凭据聚合；`avg_ms` 只算 ok 与 error）；非 PG 存储返回 503/`2001`。
- `feat(alembic)`：迁移 `0002_kb_mcp_trace`，含 4 个索引与 `trace_id` 唯一约束。
- `docs`：`kb-admin-api.md` §4.9、`mcp-tools.md` §5、`ENVIRONMENT.md` 的 `MEMHUB_KB_TRACE_SPOOL` 已同步；规格 §2.1 索引改写为升序 B-tree（列表倒序由反向扫描满足），§6.2 补 `avg_ms` 口径。ADR-0014 仍为 `proposed`，待负责人裁决。
- `test`：新增 `tests/contract/test_mcp_trace.py`（14 个用例，覆盖规格 §9.1–§9.4 的 1–13 条）；`test_kb_migrations.py` 与 `test_kb_models.py` 的表清单补入 `kb_mcp_trace`。
- 验证（2026-11-25，本地，`MEMHUB_TEST_DB_URL` 指向 `memhub_dev`，单进程）：全量 `pytest` 558 passed / 1 skipped / 1 failed，失败项为 `test_kb_models.py` 硬编码「恰好 6 张表」，补入 `kb_mcp_trace` 后重跑 `test_kb_models.py` + `test_mcp_trace.py` + `test_kb_migrations.py` 共 31 passed（修正后未再跑全量）；`ruff check`、`ruff format --check`、`mypy src`（50 files）、`check_async_io.py`、`check_no_raw_sql.py`、`check_document_format.py`、`check_agent_entrypoints_sync.py` 通过，`check_document_ownership.py --changed` 退出码 0。
- 未做：管理台「调用轨迹」页面（规格 §7，验收 14–17 的页面部分）与 MCP 发现层改进，另分支处理。
## 2026-11-25（`.env.example` 键名同步到 `.env`）

- `docs(governance)`：`CLAUDE.md` / `AGENTS.md` §2 新增硬约束：`.env.example` 新增或重命名键名时，必须在同一次变更里把该键同步写入本机 `.env`，值未知就先留空（`KEY=`），不得猜测值或沿用其他键的值。`.env` 被 Git 忽略，值不进仓库。ADR 检查：未命中（只约束本机环境文件的维护动作，不涉及部署拓扑、契约或密钥边界）。验证：纯文档修订，无业务 RED；`check_document_format.py`、`check_agent_entrypoints_sync.py`、`check_env_example_keys.py`、`check_adr_governance.py`、`check_document_ownership.py --changed` 与 `git diff --check` 均通过。该规则只约束此后的变更，不回填既有缺口。

## 2026-11-26（补齐采集源原始队列清理接口）

- `fix(ingest)`：实现 `DELETE /ingest/source/{source_id}?device_id=<id>&purge=true`，仅接受 provision token。先核对三个队列根下所有待删文件的设备和源，再清理文件、刷新配额缓存；保留已有知识、游标、去重与批次状态。成功（含空清理）记录 `ingest_purge` 审计。删除路径不再直接引用 Windows 专有的 `stat.FILE_ATTRIBUTE_REPARSE_POINT`（改 `getattr` 安全读取），避免 Linux/macOS 上抛 `AttributeError`。
- `docs`：采集 API 契约升 0.9，索引升 0.13；同步源注册表与环境键说明。
- 验证（2026-11-26，测试库 `memhub_dev`）：RED：新增清理用例因路由缺失返回 404，归属冲突与缺设备参数用例随后分别捕获误删（200）和错误信封（422），跨平台回归用例在旧实现下报 `AttributeError`。GREEN：`pytest tests/unit tests/contract -q --tb=line` 为 562 passed / 1 skipped；本地 `curl.exe` 注册、推送、游标、清理、重复清理与游标保留冒烟通过；`ruff check src tests scripts alembic`、同目录格式检查及 `mypy src` 通过。


## 2026-11-25（投影子系统下线：图谱与检索直读 PG）

- `refactor(kb)`：删除 `memhub/kb/projection.py` 与 `tests/contract/test_kb_projection_pg.py`；kb-api 去掉 `GET /api/v1/kb/projection`、`GET|POST /api/v1/kb/rebuild` 与 `_GraphRestarter`，`healthz` 改为只返回 `{ok, store, nodes}`（`store` 恒为 `pg`）。`archive.projection_dirty()` / `clear_projection_dirty()` 与 `PgKnowledgeStore.latest_write()` 一并移除；`archive.MARKER` 保留为历史 journal 的最后一个步骤，恢复流程按原样重放。
- `refactor(cli)`：删除 `memhub project` 与 `memhub serve` 子命令及 `_serve_env`；`memhub kb` 只接受 `--port` / `--web-dist` / `--data-dir`，不再读取或导出 `MEMHUB_KB_GRAPH` / `MEMHUB_KB_AUTO_REBUILD` / `MEMHUB_KB_GRAPH_PORT`。`recover-kb-archive` 的成功提示不再要求重建投影。
- `refactor(deploy)`：`compose.yml` 删除 `explorer`（`legacy` profile）；`Dockerfile.kb` 的 CMD 去掉 `--graph-out`；`deploy/README.md` 删除 rebuild timer 与 explorer 端口/回退说明；`docs/tech/ENVIRONMENT.md` 与 `.env.example` 删除三项投影键。
- `refactor(web)`：删除投影状态横幅、侧栏「重建投影」入口、`Projection` 类型与 `projection`/`rebuild` 客户端方法，`healthz` 类型改为 `{ok, store, nodes}`；删除无引用的 `VITE_GRAPH_URL` 声明。
- `docs`：契约索引升 0.12，`kb-admin-api.md` 升 0.4（删除 §4.8 投影并重排前端小节、更新不变式），`node-schema.md` 升 0.4（§6 改为「不生成文件投影」），`architecture.md` / `DEVELOPMENT.md` / `deploy/README.md` / `web/README.md` / 根 `README.md` 同步；ADR-0013 后果段记录负责人确认删除。
- `test`：新增 `test_healthz_has_no_projection_state`、`test_projection_routes_are_removed`、`test_projection_subcommands_are_removed`、`test_kb_console_rejects_removed_projection_flags`；`test_pipeline.py` 的投影用例改为断言合并后的边已按完整 id 落库；删除 `test_serve_env.py`（被测函数已移除）。
- 验证（2026-11-25，本地，`MEMHUB_TEST_DB_URL` 按直连端点单独注入）：RED——改动前四个目标用例分别因 healthz 含 `projection`、投影/重建路由仍存在、`project`/`serve` 仍被识别、`kb` 仍接受 `--graph-out` 等参数而失败；GREEN——全量 `pytest` **545 passed / 1 skipped**；`ruff check src tests scripts alembic`、`ruff format --check src tests scripts alembic`、`mypy src`（47 files）、`check_env_example_keys.py`、`check_document_format.py`、`check_document_ownership.py --all`、`check_agent_entrypoints_sync.py`、`check_adr_governance.py` 全绿；`web` 的 `tsc -b` 通过。`ruff check .` 另在 `.claude/hooks/guard-git-write.py`（本分支未改动的已提交文件）报 ISC004，属既有问题，未在本分支处理。
- `chore(deploy)`：新增 `deploy/lock-kb.txt`——kb 镜像的完整依赖锁（worker 锁的 60 项 + `mcp==2.3.0` 与其 15 项传递依赖：`mcp-types` / `httpx2` / `sse-starlette` / `pyjwt` / `cryptography` / `jsonschema` 生态 / `cffi` / `pycparser` / `pywin32`）；与 `lock-worker.txt` 的差异仅 mcp-http 闭包。锁由本机 venv 的 `importlib.metadata` 版本仿真生成；**权威锁仍须发版时在镜像内 `pip freeze` 重出**。依赖：`engine` extra 仍保留 `semantica`（已无代码引用）与 `python-multipart`（上传必需）；移除 semantica 需同时重出锁文件与离线 wheelhouse，按独立任务处理。


## 2026-11-25（模型边界统一把时间归一为 UTC）

- `fix(contract)`：`NodeFrontmatter` 的 `created_at` / `updated_at` / `valid_from` / `valid_until` / `occurred_at` / `decided_at` 增加 UTC 归一校验：naive 值按 UTC 补齐，带偏移的换算到 UTC。此前 API/MCP/CLI 传入裸日期（如 `valid_until: '2026-11-21'`）会得到 naive datetime，写进 `timestamptz` 时按会话时区（生产 +08）解释，落成前一天 16:00Z——与迁移写库缺陷同源，只是入口不同。迁移侧的局部修复保留（解析行也要守同一口径），模型边界覆盖运行态。
- `docs`：`node-schema.md` 升 0.3，新增「时间语义」小节；契约索引升 0.11。`source[].captured_at` 以原始文本存 JSONB，与既有行比对绑定，不在归一范围内。
- `test`：`test_models.py` 新增 `test_naive_times_are_normalized_to_utc`（六个字段的 naive 补齐与偏移换算）；`test_kb_pgstore.py` 新增 `test_runtime_write_normalizes_naive_time_to_utc`（会话时区钉成 +08，裸日期经 `PgKnowledgeStore.write` 回读为 UTC 零点）。
- 验证（2026-11-25，本地，`MEMHUB_TEST_DB_URL` 直连 `memhub_dev`）：RED——两个新用例 2 failed，PG 用例实际回读 `2026-11-20 16:00:00+00`；GREEN——`test_models.py` + `test_kb_pgstore.py` 合计 27 passed。

## 2026-11-25（迁移写库把 naive 时间钉成 UTC）

- `fix(migrate)`：`parse_tree` 产出的节点时间（`valid_from` / `valid_until` / `occurred_at` / `decided_at` / `created_at` / `updated_at`）与归档 `deleted_at` 统一先补成 UTC 再进写库计划。frontmatter 的裸日期（如 `valid_until: '2026-11-21'`）解析出 naive datetime；`timestamptz` 列会按**会话时区**解释 naive 值，生产迁移容器是 +08，落库变成 `2026-11-20T16:00:00Z`，而磁盘侧哈希按 UTC 零点算——`--verify-only` 对这类节点永远报内容不一致。规格 [kb-pg-migration-spec](plans/kb-pg-migration-spec.md) §3 的口径本来就是「所有时间 `timestamptz`，一律 UTC」，本次让写库侧遵守它。运行态写入路径（kb-api / MCP）不在本次范围。
- `test`：`test_migrate_apply.py` 新增 `test_naive_frontmatter_time_is_written_as_utc`，用裸日期 fixture 并把会话时区显式钉成 `Asia/Shanghai`（不依赖跑测机器默认时区），断言 `kb_nodes.valid_until` 回读为 `2026-11-21T00:00:00Z` 且 `diff_plan` 无差异。
- 验证（2026-11-25，本地，`MEMHUB_TEST_DB_URL` 指向 `memhub_dev`，按直连端点覆盖隧道口）：RED——新用例 1 failed，实际落库回读 `2026-11-20 16:00:00+00`；GREEN——同用例 1 passed。`tests/unit/test_migrate_knowledge.py`、`tests/unit/test_migrate_verify.py`、`tests/unit/test_cli_migrate_kb.py`、`tests/contract/test_migrate_apply.py`、`tests/contract/test_kb_migrations.py` 合计 56 passed。
- 生产影响：修复只对**修复后的写库**生效。已经用旧代码写入的 `valid_until` 错位行只有一条（`memhub/fact/knowledge-source-directory-structure-export-memhub`）；markdown 源已按授权删除，不能重写，只能单行订正。该订正已于 2026-11-25 15:30 按负责人指令在服务器执行（先落全库 `pg_dump` 备份，再 `UPDATE kb.kb_nodes SET valid_until = timestamptz '2026-11-21T00:00:00+00:00'`，`revision` 未改），随后对备份 tar 中的 728 个 md 重跑 `--verify-only`：`EXIT=0`，逐节点、逐边一致。728 个节点中只有这一条用了裸日期，其余时间均带 `Z`，不是普遍问题。

## 2026-11-25（Alembic 入口归一化 DSN 方言）

- `fix(alembic)`：`alembic/env.py` 把 DSN 归一化成 psycopg 3 方言（复用 `memhub.kb.session` 的同一函数，公开为 `psycopg_dsn`）。此前 `postgresql://` 直接交给 `engine_from_config`，SQLAlchemy 会按默认方言去找 psycopg2；镜像里只有 psycopg 3，`alembic upgrade head` 在连库前即以 `ModuleNotFoundError: psycopg2` 失败。生产切换时是用 `postgresql+psycopg://` 临时绕过的；修复后 `deploy/README.md` 的一次性容器命令按原样可用。运行态异步引擎行为不变。
- `test`：`test_kb_migrations.py` 新增 `test_online_path_normalizes_plain_dsn_to_psycopg3`，在 `engine_from_config` 处截获交给 SQLAlchemy 的 URL，断言已带 `+psycopg` 且不连库；先观察 RED（原始 URL 断言失败）再实施。
- `docs`：`ENVIRONMENT.md` 说明该 DSN 可写 `postgresql://`，由入口归一化。
- 验证（2026-11-25，本地）：RED——`pytest ... -k online_path` 1 failed，断言打印未归一化的 `postgresql://`；GREEN——同命令 1 passed，`test_kb_migrations.py` 与 `test_kb_session.py` 合计 13 passed / 3 skipped（无 `MEMHUB_TEST_DB_URL`，PG 用例按约定 skip）。

## 2026-11-25（kb 容器独立 env_file，隔离运行态凭据）

- `fix(deploy)`：`compose.yml` 的 kb 服务改用独立 `/etc/memhub/env.kb`，不再继承默认 `/etc/memhub/env`——受限的 kb 容器不应拿到 `MEMHUB_DB_URL`（运行态全权角色）、`PGPASSWORD`、LLM 凭据与设备 token 密钥。`env.kb` 至少写 `MEMHUB_KB_DB_URL`；`/mcp` 入口需要 `MEMHUB_MCP_GRANTS`，另按需拷 `MEMHUB_LOG_LEVEL` / `MEMHUB_KB_AUTO_REBUILD` / `MEMHUB_QUEUE_MAX_BYTES` / `MEMHUB_KB_HTTP_PORT`。
- `docs(deploy)`：README 运行形态表与「知识真源切换」第 1 步补充 `env.kb` 的建法与键范围；部署顺序第 3 步加入前置确认。
- 验证（2026-11-25，本地）：`docker compose config` 以临时 stub env_file 通过，解析后 kb 的 environment 只含 stub 中的 `MEMHUB_KB_DB_URL`（证明不再继承共享文件）；`check_document_format.py` / `check_document_ownership.py` / `check_agent_entrypoints_sync.py` 通过。本项为配置与文档变更，无法制造业务 RED，按 SDD 例外处理。

## 2026-11-25（Alembic 版本表显式落 `kb` schema）

- `fix(alembic)`：`alembic/env.py` 给所有 `context.configure(...)` 显式传 `version_table_schema`——生产路径（未注入连接，`MEMHUB_KB_MIGRATE_DB_URL` 带外执行）固定 `kb`，不再依赖角色 `search_path` 兜底；注入连接（测试隔离、`migrate-kb`）跟随该连接当前 schema，隔离用例不写进 `kb`（ADR-0013 §6）。
- `fix(alembic)`：`--sql` 离线模式优先使用调用方注入的 `sqlalchemy.url`，再退回 `MEMHUB_KB_MIGRATE_DB_URL`。
- `test`：`test_kb_migrations.py` 新增离线 SQL 断言（`kb.alembic_version` 出现、`public.alembic_version` 不出现）。
- 验证（2026-11-25，本地）：`pytest tests/contract/test_kb_migrations.py` 4 passed；全量 `pytest` 545 passed / 1 skipped；`ruff check`、`ruff format --check`、`mypy src`（48 files）、`check_no_raw_sql.py`、`check_async_io.py` 全绿。

## 2026-11-25（写入审计落 `kb_write_audit`）

- `feat(kb)`：`PgKnowledgeStore` 新增 `record_write_audit()`，向 `kb_write_audit` 写一条不含正文与 token 的审计（规格 §3.6）；审计自成事务，落库失败按原路径上抛，不静默丢记录。
- `feat(mcp)`：三个写工具（`kb_write_candidate` / `kb_update_candidate` / `kb_deprecate`）每次写尝试（含被拒的）落一行审计：`actor=mcp:<grant_id>`、`project`、`node_id`、`action`（create/update/deprecate）、`result=ok` 或拒绝原因码；文件存储（测试夹具）仍只留日志。
- `feat(ingest)`：每次采集决策（接受、拒绝与重放）落一行审计：`actor=device:<device_id>`、`project`、`action=ingest`、`result=ok` 或拒绝原因码；原 `memhub.ingest.audit` 日志保留为运维旁路。
- `docs`：`mcp-tools.md` 0.6 与 `ingest-api.md` 0.8 记审计落库语义，契约索引升到 0.10。
- `test`：新增 `tests/contract/test_kb_write_audit.py`（三写工具的成功/拒绝/越权审计与内容不泄漏）与采集审计落库断言。

## 2026-11-25（运行时强制 PG：投影、MCP、CLI、worker 接线）

- `feat(kb)`：运行入口统一经 `create_runtime_store()` 从 `MEMHUB_KB_DB_URL` 构造 `PgKnowledgeStore`；kb-api、MCP、worker、CLI 缺 DSN 时抛 `KbDsnMissing`，不再退回 `knowledge/` 文件存储。`KnowledgeStore` 保留给测试夹具、迁移工具与一次性迁移源。
- `feat(kb)`：投影改为存储无关——`build_graph` 经 `edge_lines()` 读节点与边，PG 版 `save_projection` 跳过文件锁与脏标记；投影过期判断改用 `latest_write()`（取 `kb_node_revisions` / `kb_edges` 的最大时间），不再依赖文件 mtime。
- `feat(worker)`：`WorkerConfig` 持有存储对象而非真源目录；merge 的锁与目标校验改用 `store.write_scope()` / `store.guard_write()`，PG 版一次写入即一个事务；新建节点显式带上完整 id，满足 PG 写入的 id 一致性校验。
- `feat(cli)`：`ingest` / `project` / `mcp` / `kb` / `worker` 去掉 `--knowledge-dir`，完成输出与冒烟日志改为 `真源=PG（schema kb）`；`recover-kb-archive` 仍保留目录参数（文件版归档是迁移期工具）。
- `feat(kb)`：`TargetRegistry` 改为接收登记状态来源（文件或 PG 存储），worker 与采集共用同一判据。
- `feat(ingest)`：采集目标的「已登记且活动」改为读 `kb_projects`（存在行且 `archived_at` 为空），不再读 `MEMHUB_KNOWLEDGE_DIR` 的目录与 `.kbs.json`；`create_app` 经 `create_runtime_store()` 构造 PG 存储，缺 `MEMHUB_KB_DB_URL` 启动即抛 `KbDsnMissing`，应用自建引擎在 lifespan 关闭。`/ingest/raw` 与 `/ingest/projects` 共用同一判据；归档事务 `pending` 时仍返回通用 `500/2001`。采集侧只读该表，不写知识真源。
- `test(kb)`：新增 PG boot / 投影 / worker 接线用例（缺 DSN 启动失败、worker 写库不落 markdown、PG 归档与 pending 事务的暂缓与隔离）；采集契约用例改用独立 PG schema 登记目标，覆盖归档后重放拒绝与未完成归档事务的通用错误；PG 夹具上移到 `tests/conftest.py` 供 unit 与 contract 共用。
- `docs`：`ENVIRONMENT` 更新 `MEMHUB_KNOWLEDGE_DIR` 的读取方（仅迁移/恢复工具）与 `MEMHUB_KB_DB_URL` 的适用范围（含 ingest）；`ingest-api` 契约升到 0.7，说明登记判据改读 `kb_projects`。
## 2026-11-25（部署与锁文件对齐 PG 真源）

- `feat(deploy)`：`Dockerfile.kb` 改装 `memhub[postgres,engine,mcp-http]`，移除 `--knowledge-dir`，烘入 `alembic.ini` 与 `alembic/`——Alembic 由一次性容器带外执行（ADR-0013 §4，不在容器启动时跑），运行入口只认 `MEMHUB_KB_DB_URL`。
- `docs(deploy)`：README 新增「知识真源切换（markdown → PG，一次性）」小节：建对象与角色 → 停写 → Alembic 建表（一次性容器，运行位置留有备选宿主 venv 的待负责人裁决项）→ `migrate-kb` dry-run/写库/`--verify-only`（强制 `--archives migrate`）→ 备份 → 负责人授权删 markdown → 强制重建三容器 → 回滚与验收；`project` 等 timer 命令去掉 `--knowledge-dir`，kb-api 条目补连 PG 说明。
- `chore(deploy)`：`lock-ingest.txt`（23→28 项）与 `lock-worker.txt`（55→60 项）补 `alembic 1.20.1` / `SQLAlchemy 2.0.58` / `greenlet 3.5.6` / `Mako 1.4.3` / `MarkupSafe 3.0.4`，纯增不改既有版本。注意：本机 Docker daemon 未运行，锁由离线 `pip install --target`（多 `--platform` 标签）仿真生成；**权威锁仍须发版时在镜像内 `pip freeze` 重出**，同时 `deploy/dist` 的 wheelhouse 需补上述 3 个 wheel 并按最终发布提交重打 memhub wheel 与 `SHA256SUMS`/`MANIFEST`。
- `docs(compose)`：kb 服务注释改为「连 PG：`MEMHUB_KB_DB_URL` 经 env_file 注入，缺失启动即失败」，图谱页数据来源改为 `/api/v1/kb/graph` 直读 PG。
- `docs(guides)`：DEVELOPMENT §1/§2/§3/§9/§9.1/§10 按运行态 PG 重写（安装 extra、目录分层、PG 契约测试命令、端到端闭环走 `--create-project`/`project --out`、一次性迁移与归档恢复命令、MCP 不再传 `--knowledge-dir`）。
- 验证（2026-11-25，本地）：`docker compose -f deploy/compose.yml config` 通过（临时 stub `env_file`，验后删除）；锁文件为离线 `pip install --target`（ingest 侧 29 wheel、worker 侧 78 wheel 的安装产物，去掉 win32 专属的 `colorama` / `win32_setctime` 与 ingest 的 `tzdata`）导出，SQLAlchemy 保持 2.0.58（下载器给出的 2.1.9 被弃用，符合 `<2.1` 上限）。本次未改 Python，`ruff` 不适用；`check_document_format.py --staged`、`check_document_ownership.py --staged`、`check_env_example_keys.py`（29 键一致）与 pre-commit 全钩子通过。全量 pytest 未在本机重跑（避免与 peer 并发共用测试库），以 peer 分支 `d954c3b`/`ecd380a` 的 504 passed/1 skipped 为准。

## 2026-11-24（kb 迁移工具：写库半段与逐节点校验）

- `feat(migrate-kb)`：新增 `src/memhub/kb/migrate_db.py`，把解析出的迁移计划写进 `kb_projects` / `kb_nodes` / `kb_edges` / `kb_archives`，并回写回收站的删除留痕到 `kb_node_revisions`。写入顺序固定为项目 → 节点 → 边 → 归档（可选）→ 修订，单事务提交；`kb_projects` 先于 `kb_nodes`，因为 ORM 模型之间没有 relationship、flush 顺序不由依赖推断。`apply_plan` 按主键 / `(source, predicate, target)` 三元组 upsert，重复运行计数不变（规格 §5 第 9 步）。
- `feat(migrate-kb)`：`--verify-only` 改为逐节点、逐边比对（规格 §5 第 7 步）：`read_stored` 回读库内全部行，`diff_plan` 用与解析侧同一个 `node_revision` 重算内容哈希后比对，差异分九类（项目缺失/多余/变更、节点缺失/多余/变更、边缺失/多余、归档快照不符）逐项打印，不一致非 0 退出。归档快照默认不比，`--archives migrate` 时才对 `bytea` 快照的 sha256。悬空边原样写入并参与比对，不因校验丢弃。
- `feat(cli)`：`memhub migrate-kb` 新增 `--schema`，目标 schema 由 `search_path` 决定，缺省不设（生产用专用 schema `kb`，测试可指向独立 schema）。`--delete-source` 仍不执行删除：校验通过后打印需负责人授权、返回 3，源文件不动（ADR-0013 §9）。
- `fix(migrate)`：内容哈希按 UTC 归一。`timestamptz` 按会话时区回读，磁盘侧的 `+08:00` 与库侧的 `+00:00` 表示同一时刻，不归一就会让同一条记录在两侧算出不同 `revision`；不带时区的时间按 UTC 处理。
- `fix(migrate)`：项目行的时间取磁盘事实而非扫描时刻。登记缺 `created_at` 时回落到该库节点时间的极值（无节点才用纪元时间），`updated_at` 取 `created_at` 与节点极大值的较大者；原先用扫描时刻会让每次解析都得到不同的项目哈希，`--verify-only` 永远报内容不一致。
- `fix(migrate)`：回收站 `.meta.json` 改为相对知识库根解析。原先按进程 CWD 拼路径，文件永远找不到，删除审计（`actor` / `reason`）静默丢失，而迁移后 `kb_node_revisions` 是唯一的删除留痕。
- `fix(migrate)`：归档行带解析侧的辅助键（`snapshot_sha256`、`name`），直接进 upsert 会因不存在该列而编译失败；写库前按目标表的真实列名过滤。
- `fix(migrate)`：迁移的「未完成归档事务」判定只认 `_kb_archives/pending.json`。原先复用了 `archive.projection_dirty`，它把 `pending.json` 与 `projection-dirty` 一并算作阻断；而整库归档**成功后**也会留下 `projection-dirty` 直到投影重建，结果是归档过任何库的服务器永远报「存在未完成的归档事务」而无法迁移。新增 `archive.pending_transaction` 区分两者，`projection_dirty` 的既有调用方不变。
- `fix(migrate)`：整库归档后目录与登记都已消失，但 `_trash` 里的节点还在盘上；这些节点的 `project` 外键指向的行原先不建，写库直接 `kb_nodes_project_fkey` 失败并整体回滚。现在按归档头复现归档库的 `kb_projects` 行（`name` 取归档头显示名，`archived_at` 取 `deleted_at`，`updated_at` 不早于归档时间），并保证任何节点行引用的库都有对应行；解析顺序改为先扫归档再建项目行。仅登记无目录、无节点、无归档的库仍只进 `missing_projects`，不建行。
- `fix(migrate)`：已恢复的归档目录不再算坏包。恢复成功会删掉 `active.json`、留下 `snapshot.zip` 与目录，归档是否生效以 `active.json` 为准（与 `catalog.list_archives` 同口径）；原先把它报进 `invalid_archives` 并阻断写库，「归档过再恢复」的服务器因此永远无法迁移。`active.json` 在而快照缺失仍按坏包阻断。
- `docs(guides)`：开发指南 §3 新增 PG 契约测试命令，说明 `MEMHUB_TEST_DB_URL` 未设置时用例 skip、skip 不计为通过，且只单独导出该键、不整份 source 环境文件（会顺带覆盖运行态 `MEMHUB_DB_URL` 与 `PG*`，测试结果不可信）；§4 验证矩阵新增「kb 存储 / 迁移 / 契约夹具」一行；§9 增补一次性迁移的端到端命令。
- 迁移态（记录见本条，规格 [kb-pg-migration-spec](plans/kb-pg-migration-spec.md) 为当次权威）：
  - 当前真实形态：知识仍以 markdown 为运行时真源（`KnowledgeStore`、跨进程写锁、`.kbs.json` 登记），`kb_*` 六张表已建好、迁移工具可写可校验，但运行时读写尚未切换。
  - 最终目标：PostgreSQL 的 `kb_*` 为唯一真源（ADR-0013），服务器 markdown 迁移后删除，仓库只留 `tests/fixtures`。
  - 迁移步骤与依赖：建表（Alembic 基线）→ `migrate-kb` 写库 → `--verify-only` 逐节点通过 → `pg_dump` 与 `knowledge/` 打包备份 → 负责人授权后删除 markdown → 运行时切到 PG 存储层 → 删除文件退路。
  - Consumer：kb-api 与 MCP 读取、worker 提炼写入、管理台删除/归档、采集目标校验；切换点由存储层的 `PgKnowledgeStore` 决定，逐个 consumer 改由同一存储协议承接。
  - 兼容调用量：迁移工具在 dev 库 `memhub_dev` 上实测通过；生产 `knowledge/` 的节点量、逐库边数与悬空边数须在服务器上以 `--dry-run` 现场统计，本仓库无该数据。
  - 退出门禁与删除时点：逐节点、逐边哈希全部一致 + `pg_dump` 与 markdown 打包备份完成（ADR-0013 §9）；删除动作由负责人在服务器执行或明确授权，本仓库不做。
- 验证（2026-11-24，本地，只单独导出 `MEMHUB_TEST_DB_URL`，未写进任何文件）：`pytest -q` 全量 `445 passed, 1 skipped`（136.96s；skip 为 Windows 下无法建符号链接的既有用例）；同一命令不设该键时 `407 passed, 35 skipped`，PG 用例整组 skip、按规格 §8.10 不计为通过。`ruff check src tests scripts alembic deploy` 与 `ruff format --check` 通过（98 文件）；`mypy src` 无问题（45 个源文件）；七个治理门禁通过。`memhub migrate-kb` 对 dev 库实测（含「先软删节点、再整库归档」的合成树，Alembic 基线建出的全新 schema）：写入 → 校验通过 → 再写入 → 再校验通过 → `--delete-source` 返回 3 且源文件不动；库内该归档库的 `kb_projects.archived_at` 非空、显示名取归档头，回收站节点与归档快照均落库。上面均为本地结果，不含生产数据与服务器操作。

## 2026-11-24（MCP 写候选与候选区闭环）

- `feat(mcp)`：新增 `kb_update_candidate` 与 `kb_deprecate`（ADR-0012），补齐候选区写闭环，仍然不碰 canonical。两者都要求 `mcp:write` 与 `expected_revision`（取自 `kb_read` 新增返回的 `revision`）；检查与写入在同一把跨进程写锁内完成，不符返回 `409/1010` `revision_conflict`，目标不是 `tier=candidate` 返回 `409/1010` `not_candidate` 且不改文件。更新只允许 `title/body/tags/confidence`，并对更新后的标题与正文重跑内容门槛与同项目正文哈希去重；废弃保留文件、`reason` 写入 `deprecated_reason` 并追加 `## 废弃说明`，`superseded_by` 可选（指向自己或不存在分别返回 `superseded_by_invalid` / `superseded_by_unavailable`）。
- `feat(contract)`：`NodeFrontmatter` 新增可选字段 `deprecated_reason`；`tier=deprecated` 的约束从「必须有 `superseded_by`」放宽为「`superseded_by` 或 `deprecated_reason` 至少一项」。已存在且不含该字段的节点不受影响。
- `feat(mcp)`：`kb_read` 返回 `revision`，作为两个写工具的前置条件来源；`tools/list` 对 `mcp:write` 由五个工具变为七个（`mcp:read` 仍是四个）。三个写工具的审计日志共用一条记录格式。
- `docs`：MCP 契约升到 0.4（候选区闭环）；跨端契约索引升到 v0.8；`node-schema` 补 `deprecated_reason`；新增 ADR-0012 并在 ADR 索引登记。
- 发布（2026-11-24，回滚目录 `memhub-release-62bd6fb-20261124-095911`）：release 提交为 merge `62bd6fb`（父 `b8bd53c` + `ed3c4ec`），内容含 `25f3bb6`、`ec74c07`、`2b2889e`、`7536c96`；发布前线上为 `7536c96`（三容器，`backup-62bd6fb-pre` 标签镜像构建于 11-23 11:32 CST），`2b2889e` 与 `25f3bb6` 均属本次首发；`main` 与 `dev`（`ed3c4ec`）均已推送 `origin`。`deploy/dist` 按 `62bd6fb` 重建：wheel `0f3b1f08…`，`SHA256SUMS` 共 162 项，本地与服务器均 162/162 通过；wheelhouse-ingest 26 个 wheel、wheelhouse-worker 75 个（补入 `mcp` 2.3.0 及其 Linux 依赖）、web-dist 61 个文件。三镜像 `memhub/app:62bd6fb`（`9c43009a281d…`）、`app-worker:62bd6fb`（`4ed186b2be22…`）、`app-kb:62bd6fb`（`c88245f69d32…`）以 `--network=none` 离线构建，2026-11-24T02:33Z（CST 10:33）以新镜像启动，回滚标签 `backup-62bd6fb-pre`。nginx vhost 换为 `62bd6fb` 版本（新增精确 `location = /mcp`，16 KiB 上限、不挂 `auth_request`），`nginx -t` 通过后 reload。`MEMHUB_MCP_GRANTS` 单条记录 scope 由 `mcp:read` 改为 `mcp:write`，摘要、到期与 8 个库不变。线上 compose 含本地增量（oauth-egress 容器、代理环境变量），只替换三个 image 标签，未整份覆盖；knowledge/data 内容、配额与 `memhub-rebuild.timer` 未动。
- 验收（2026-11-24）：生产 kb/ingest `healthz` 200、portal `/` 200、`/mcp` 无凭据 401，三容器 healthy，worker 窗口外休眠。隔离夹具（合成 alpha/beta、独立端口、验收后销毁）：`mcp:write` 凭据 `tools/list`=7 且 `readOnlyHint` 为 `[T,T,T,T,F,F,F]`，`mcp:read` 凭据 `tools/list`=4 且看不到写工具；写链路 `kb_write_candidate` → `kb_read` 取 `revision` → `kb_update_candidate` 成功 → 旧 `revision` 再更新得 `1010 revision_conflict` → `kb_deprecate` 后 `tier=deprecated` 且 `deprecated_reason` 有值。`GET /ingest/projects` 在隔离夹具上实测返回 `writable_only: true`，契约 0.6 生效。生产写侧未做探针（未用生产 token、未临时加摘要），生产 `tools/list`=7 待用户以自己持有的凭据确认。以上部署与夹具验收由云主机运维会话执行并报告，本仓库未复跑。

## 2026-11-24（MCP 写候选）

- `feat(mcp)`：开放第一个写工具 `kb_write_candidate`（ADR-0011）。新增 `mcp:write` 作用域（隐含读），`tools/list` 按作用域裁剪；只创建 `tier=candidate`，slug 命中 canonical/deprecated 返回 `slug_conflict_canonical`、命中已有 candidate 返回 `slug_conflict_candidate`、归一化正文哈希命中返回 `content_duplicate`。证据必填，复用 `SourceRef` 形状，做结构与归属校验（拒绝绝对路径、`..` 穿越、指向未授权库、敏感串形态）；不做可解析性校验。内容门槛覆盖可机械识别的垃圾（过短、寒暄/确认集合、日志倾倒）；每日上限 50 次/凭据/UTC 日，按新节点 `source` 中的 `mcp:<grant_id>` 标记现算。写成功自动 git commit，message 含工具名与调用者。canonical 修改与治理组其余工具仍关闭。
- `docs`：MCP 契约升到 0.3（写候选）；跨端契约索引升到 v0.7；环境键说明更新 `MEMHUB_MCP_GRANTS` 的 scope 取值。

## 2026-11-24（采集目标校验与会话候选门禁）

- `docs(governance)`：分支与发版规则调整：`main` 为稳定分支，只有负责人明确允许后才能合入，发版只从 `main` 出；`dev` 为日常集成分支，worktree 从 `dev` 创建，验收后合回 `dev` 并清理；同步 `AGENTS.md`、`CLAUDE.md` 与开发指南 §6。
- `fix(ingest)`：采集写的目标边界收敛为「显式 + 已登记 + 活动」，按 `data.reason`（missing/reserved/invalid/unregistered/inactive/target_conflict）区分拒绝；不再按来源命名兜底建库，每次采集写一条不含正文与 token 的审计。列表只返回已登记且活动的目标；拒绝不推进游标，也不追加重放内容。
- `fix(worker)`：调用模型前和真源写锁内复核队列记录与目标；无法验证的旧目标不改投。明确拒绝则保留原始字节于 `pending_review/`，暂不可验证时留队。
- `fix(session)`：会话 JSONL 不回退到原文；只接受有可核对引用的可复用候选，压缩可识别的跨块重复，允许零候选。文档与 wiki 提炼规则不变；Fake 验证规则，不代表真实模型精度。

## 2026-11-20（MCP：首版四个只读工具 + 本地 HTTP 入口）

- `feat(mcp)`：`kb_search` / `kb_read` / `kb_related` / `kb_audit_list` 收敛到共享工具层：严格参数校验（拒绝未知字段与类型转换）、先判授权范围再读盘、读取持共享写锁。受限调用不返回来源引用与跨库引用，不把短别名在子集内重新绑定，丢弃无法安全归属的边；受限审计只是范围内的视图，不替代全库审计。
- `feat(mcp)`：kb-api 在精确 `/mcp` 提供无状态 Streamable HTTP（JSON 响应、16 KiB 请求体上限、同进程单 POST 串行、仅接受机器客户端）。协议解析交给官方 `mcp==2.3.0`；新增可选 extra `mcp-http`，基础安装、stdio 与管理台不引入该 SDK。未配置凭据时 `/mcp` 及其子路径一律 404，不落到管理台 SPA。
- `feat(mcp)`：`MEMHUB_MCP_GRANTS` 只保存令牌 SHA-256 摘要、`mcp:read` 作用域、UTC 有效期与库名单；每个请求重算范围，授权上下文缺失时按空权限处理。浏览器 Cookie 与 `/ingest/*` 的 device token 不授予 `/mcp` 权限（ADR-0003）。吊销 = 删除摘要并重启，无在线发放接口、不改数据库。
- `docs`：同步 MCP 契约 §4、架构中的承载进程、环境键集、开发指南（安装与验证矩阵）和部署端口说明。
- 状态（2026-11-21 更新）：已合入 `main`（提交 `07d7bc8`），已随生产发布，公网 `/mcp` 已开通（据云主机运维会话报告）。目标客户端联调与容器内存预算仍未验收，见开发指南 §10.1。
- 验证（装 `mcp-http` 的环境）：`pytest -q` 全量 `229 passed, 10 skipped`，含官方 SDK 客户端经 ASGI 传输的握手、四工具发现、跨凭据库隔离与越权拒绝、参数一致性、并发 429、过期与吊销；基础环境同组 HTTP 用例跳过。Ruff check/format、装与未装 SDK 两种环境的 `mypy src`、异步 IO 检查、`git diff --check` 通过。以上验证仅在本地回环完成，不含 nginx、公网、目标客户端联调与容器内存。

## 2026-11-20（管理台：知识库归档删除、回收站分页与 GitHub 身份）

- `feat(kb)`：支持独立的整库归档与恢复。快照保留 Markdown 原始字节、库登记、库内和跨库关系；恢复时不覆盖已有库或归档期间其他库的无关改动。单节点回收站保持原有行为。
- `fix(kb/worker)`：管理端、提炼合并和投影发布共用跨进程锁；已归档的库不被队列重新建出。未完成的整库操作可用 `memhub recover-kb-archive` 核对并续做。
- `feat(kb)`：回收站接口支持 `offset`、`project`、`q`，返回过滤后 `total` 与未过滤 `total_all`；管理台改为 20 条一页的筛选列表。
- `feat(web)`：侧栏副标题改为「云端知识图谱」；通过 oauth2-proxy 注入的 GitHub 登录名显示真实用户名与头像，增加退出登录；本机直连时保留明确的未认证占位。
- `fix(deploy)`：nginx 从 `X-Auth-Request-User` 透传 GitHub 登录名，避免 GitHub provider 不提供 `Preferred-Username` 时用户信息为空；oauth2-proxy 继续启用 `--set-xauthrequest=true`。
- `docs`：同步 kb-admin API 契约，补充整库归档删除、回收站分页过滤和 `/me` 身份接口。
- 验证：`pytest -q` 全量 `213 passed, 9 skipped`；`pnpm run build` 与前端请求契约 5 项通过，保留现有图谱分包告警。Ruff、Windows/Linux 目标 mypy、异步 IO 检查和 Compose 结构校验通过。临时样本浏览器验证整库归档与恢复；真实 GitHub 登录与登出留待上线验收。

## 2026-11-20（worker：过滤 isMeta 注入，不再把技能文档当会话知识）

- `fix(worker)`：会话渲染跳过 `isMeta` 为真的事件，避免以 `user` 角色注入的技能文档混入提炼输入。只按显式标记过滤，不声称能识别所有未标记的跨会话消息或通知；工具调用标记、普通对话与输入长度策略保持不变。
- `fix(worker)`：`render_jsonl` 拆出 `render_jsonl_events(text) -> (文本, 解析事件数)`；`_document_text` 的「渲染为空退回原文」兜底改为只在解析事件数为 0（增量从事件中间切出）时生效。解析到事件但过滤后为空（整份只有注入/工具结果）时保持空文本，否则兜底会把整份 JSONL 原文连同技能手册一起喂给模型，绕过过滤。
- 本地只读复验：两份会话渲染结果均不再包含技能文档标记，未调用模型、未上传会话、未重跑或修改线上知识节点。
- 测试：`test_split_render`（isMeta 注入不混入对话）、`test_daemon`（只有注入的会话不调用模型）；全量 `185 passed, 9 skipped`。
- 发布（2026-11-20 11:22 CST）：`deploy/dist` 按 `775a406` 重建（wheel `dd8d667c…`；`SHA256SUMS` 共 155 项，本地与服务器均 155/155 通过）；ingest 镜像 `ae517124a2b3`、worker 镜像 `a13c3f9957db` 上线，kb 镜像不变；回滚标签 `backup-775a406-pre`。验收：三容器健康，`worker --once` 退出码 0。
- 存量订正（2026-11-20 13:24 CST 已执行）：本修复只对之后的批次生效，此前已在 `claude-session-4f29cd50` / `claude-session-ccfcacf9` 生成的部分节点混入注入文本。范围为 143 归档 / 53 保留（两库 43+100 归档、12+41 保留；196 个节点各出现一次），逐节点核对哈希后用 kb-api DELETE 归档到 `_trash`（可恢复），不物理删除、不整库删除；未另建 tar 备份，可恢复性依赖 `_trash` 归档。执行结果：143/143 归档成功，失败 0、跳过 0、409 0；preflight 196 条哈希全部匹配，移除相连边 98 条。复核（独立拉取）：两库剩余 12 / 41 个节点且与保留清单逐一相同，53 个保留节点 revision 与清单哈希 0 变化，归档节点 0 残留；`_trash` 共 151 个 `.md` 与 151 个 `.meta.json`（此前 8 + 本轮 143）；投影 490 节点 / 2679 边 / 0 未解析边。`stats.orphans=16` 属其它库的无边节点，与本次清理无关。

## 2026-11-20（采集归属：知识库由用户在客户端选；窗口时区；并发竞态）

- `feat(contract)`：`project` 从「协议里有、实现丢弃」变成端到端生效。规则收敛到一个地方：`KB_ID_PATTERN`（`^[a-z0-9][a-z0-9._-]{0,63}$`，真源里就是一级目录名）、`valid_project`、`sanitize_kb_id`、`resolve_project`。`sources.json` 的 `sources[].project` 在桌面端写配置时就按同一规则校验。
- `feat(ingest)`：`/ingest/raw` 接受并校验 `project`（`auto` = 不指定），落盘 payload 带上 `project`；非法值整批 `400/1003`，不静默兜底。`rawstore.save_batch` 不再丢弃该字段。
- `feat(worker)`：`process_file` 用 `resolve_project(payload["project"], source_id)` 决定写入 `knowledge/<project>/`；`auto`/缺失（旧批次）/非法值回退按白名单化后的 `source_id`——顺带堵住 `source_id` 直接拼路径的越界面。
- `feat(ingest)`：新增 `GET /ingest/projects`（已有知识库列表）与 `POST /ingest/projects`（新建知识库），设备 token 鉴权，转发同机 kb-api（`MEMHUB_KB_API_URL`，默认 `127.0.0.1:8701`），业务码透传（1010 冲突 / 1011 不存在 / 1012 非法），kb 未起返回 500/2001。桌面端据此做「被采集目录 → 知识库」下拉与「新建」。
- `fix(worker)`：窗口时区。容器默认 UTC，`--window 21:00-02:00` 实际跑在 05:00-10:00 CST（文档写的是本地时间）。新增 `MEMHUB_WINDOW_TZ`（`UTC` / `+08:00` / IANA 名，非法值退出 2），`WorkerConfig.window_tz` 参与门控；compose 生产设 `+08:00`（显式偏移，不依赖 slim 镜像的 tzdata——缺 zoneinfo 时 `astimezone()` 会静默退回 UTC）。
- `fix(worker)`：手动 `--once` 与守护进程同时处理同一文件时，后者在 `_mark_processed` 的 `AsyncPath.replace` 上 `FileNotFoundError` 打崩整轮（实测重启 1 次，同一会话被提炼两遍）。移动失败按「已被其他进程处理」跳过，不再中断一轮。
- `fix(kb)`：`KnowledgeStore.list_ids` 遍历整个 `knowledge/` 时没有跳过 `_trash/`，管理台删掉的节点会以 `_trash/<时间戳>/<原 id>` 伪节点身份重新出现在投影和图谱里（实测 8 个归档节点让投影多出 8 个 `_trash` 节点）。`TRASH_DIR` 常量收敛到 `kb/store.py`，`list_ids` 跳过它。
- `fix(ingest)`：`POST /ingest/projects` 拒绝 `id=auto`（400/1003，`data.reason="reserved"`）——`auto` 是推送侧「按源 id 归档」的保留值，建成真库会得到一个谁都没法引用的目录名；格式非法另报 `data.reason="invalid"`，客户端不必解析 message。
- 验收（客户端实测设备令牌，ccda431 线上）：`POST /ingest/projects {"id":"auto"}` → 400/1003；重复 `client-smoke` → 409/1010；`{"id":"Bad Id"}` → 400/1003。`GET /ingest/projects` 返回 7 个库（含 worker 兜底建的 `claude-session-*`），新建 `client-smoke` 后 8 个。
- `fix(kb)`：`POST /api/v1/kb/projects` 重复创建原本返回 `422/1012`（被当成参数非法），与契约的 `409/1010` 不一致，桌面端因此无法区分「id 不合法」和「已存在，可直接选用」。改抛 `ConflictError`。
- 线上数据订正：`claude-session-ccfcacf9` 的「63 个重复节点」实为陈旧投影（kg.json 在 worker 第二次写入前 7 秒重建，少了 63 个节点），重建后 149 个节点、641 全局、0 悬空边。逐对比较正文后只有 8 对语义重复，已按「保留更完整/连边更多的一份」把另一份归档到 `_trash`（可恢复），现存 141 个节点。
- 测试：`test_ingest_api`（project 落盘/非法值/代理端点/业务码透传/auto 保留值）、`test_daemon`（选库落盘、auto 回退、越界防护、窗口时区）、`test_kb_manage`（归档节点不进投影）、`test_rawstore`、`test_models`。

## 2026-11-20（修复：worker 输出预算被 thinking 吃光）

- `fix(worker)`：线上首次 `worker --once` 失败——`LLMError: 模型返回空内容（stop_reason=max_tokens, blocks=[thinking]）`。`max_tokens=8000` 是**含 thinking 的总预算**，抽取提示词下模型把 8000 全花在思考上，200 响应里只有 thinking 块、没有 text；重试 3 次都是同一结果。默认预算提到 `32000`（`llm.py` 新增 `DEFAULT_MAX_TOKENS`，`extract_document` 与 `WorkerConfig` 同步），不关闭 thinking——限制思考长度比整段关掉更保守。
- `feat(worker)`：新增可选环境变量 `MEMHUB_LLM_MAX_TOKENS`（默认 `32000`）覆盖单次输出预算；非整数或非正数按配置错误退出 2，不静默回退。同步 `.env.example` 与 `docs/tech/ENVIRONMENT.md` §2。
- 测试：`test_llm` 断言默认请求体 `max_tokens == 32000`；`test_daemon` 断言 `WorkerConfig.max_tokens` 透传到 `LLMClient.complete`。全量 `158 passed, 9 skipped`。

## 2026-11-19（发布：管理台上云，explorer 退役）

- `feat(deploy)`：新增 `deploy/Dockerfile.kb`——复用 worker wheelhouse（需要 `engine` extra 的 semantica 投影），把 `web/dist` 烘进镜像，命令为 `memhub kb --knowledge-dir /var/lib/memhub/knowledge --graph-out /var/lib/memhub/kb/kg.json --web-dist /app/web-dist --data-dir /var/lib/memhub/data`；`compose.yml` 增加 `kb` 服务（384m，实测重建 437 节点 / 2631 边峰值 143MB）。
- `refactor(deploy)`：管理台取代 explorer 挂到 `/`。explorer 服务改到 `profiles: ["legacy"]`（默认不启动），oauth2-proxy 的 `--upstream` 改到 `127.0.0.1:8701`；四服务内存上限 ingest 384 + worker 640 + kb 384 + oauth2-proxy 128 = 1536m，仍守住 1.5G 硬顶。
- `fix(deploy)`：wheelhouse 补齐 ADR-0005 异步数据层新增的运行时依赖——`sqlalchemy 2.0.58` 与 `greenlet 3.5.6`（此前 `pip install --no-index "memhub[postgres]"` 会因缺包直接失败），并换成本次发布提交构建的 memhub wheel；离线解析 `memhub[postgres]` / `memhub[postgres,engine]` 均通过。
- `fix(deploy)`：`deploy/nginx/memhub.vhost.conf` 的 `/` 与新增的 `^~ /api/v1/kb/` 都反代到 8701 并走 `auth_request /__memhub_auth`；页面未登录 302 到 GitHub，API 未登录返回 401 JSON（`1040`），fetch 不再被 302 带到 HTML 登录页。`/api/v1/`（采集）保持设备 token 自鉴权。
- `docs(deploy)`：README 更新为本版形态；明确 `memhub mcp` 是 stdio 服务、不占 8702；schema 仍只有 `0001_state`，由 ingest 启动时幂等应用，无独立迁移命令。
- `fix(deploy)`：oauth2-proxy 原先显式写了 `--scope=user:email`，覆盖掉 GitHub provider 的默认 `user:email read:org`；v7.6.0 的 `EnrichSession` 会无条件列组织（`/user/orgs`），于是回调 500 `You need at least read:org scope`。删掉该覆盖（用默认 scope），并加 `--whitelist-domain=memhub.work`，否则 `rd=https://memhub.work/` 被判非法、登录后只能回 `/`。
- `fix(deploy)`：worker 镜像缺 `prompts/`——`worker/prompts.py` 按 `parents[3]` 解析，pip 安装后落在 `/usr/local/lib/python3.12/prompts`，而 Dockerfile 只装了 wheel，首次 `worker --once` 直接 `FileNotFoundError: sessions.md`。`Dockerfile.worker` 补 `COPY prompts /usr/local/lib/python3.12/prompts`。（后续应把 prompts 作为包数据随 wheel 分发，去掉对安装路径的推断；本版按镜像修复保持与线上一致。）
- 验收（2026-11-19 19:13 CST）：首个真实设备 `APPLESAY004` 首推成功——collector `accepted 1, duplicates 0`，913,661 字节会话 → 线上 raw_store 970,899 字节（批次 JSON 信封 + 字符串转义，非 base64；e4 逐字节核对）。`/ingest/cursor`、`/ingest/raw`、`/ingest/heartbeat` 均 200。

## 2026-11-19（web：概览限高 + 图谱缩放性能）

- `fix(web)`：图谱缩放发飘/卡顿——标签更新原本在每次 `zoom` 事件全量遍历节点与边写 `data()`；437 节点 / 2631 边时单次约 9.25ms，叠加渲染超出帧预算，滚动起来像「卡住」。现在按「缩放档位 + 命中/选中集合」做签名，未跨档直接跳过：实测命中缓存 0.9ms/次，跨档时才全量重算。20 次连续缩放事件合计 12.6ms。
- `fix(web)`：全部知识库页——库分布列表限高内部滚动（`max-h-72`），库数量增长不再把概览卡片撑高；知识库卡片网格保持页面滚动，库数 >8 时出现「过滤知识库」输入框，按 id/名称/描述实时过滤。
- 验证：`pnpm typecheck`、`pnpm build` 通过；ego-browser 实测列表页概览（5 库 / 437 节点 / 2631 边 / 14 孤立）、库分布容器无溢出，图谱页连续缩放事件计时如上。

## 2026-11-19（web：全部知识库页全局概览 + 图谱滚轮缩放）

- `feat(web)`：「全部知识库」页新增全局概览——统计卡（知识库数 / 知识节点 / 关系 / 未解析边，另标注孤立节点数）、类型分布（按 `by_kind`，点击跳到 `/nodes?kind=`）、库分布（按 `by_project`，点击进入该库概览）。数据全部取自现成的 `GET /api/v1/kb/stats`，后端与契约不变；每个库仍是隔离目录，概览只做汇总。
- `fix(web)`：图谱滚轮缩放过慢——`graph-canvas.tsx` 的 `wheelSensitivity` 由 0.2 改为 cytoscape 默认 1。实测一格滚轮（deltaY=120）的缩放步长从约 0.96% 提升到约 4.7%，全局图（437 节点）从概览放大到可读标签的滚动次数约为原来的 1/5。
- 验证：`pnpm typecheck`、`pnpm build` 通过；浏览器实测 8701 列表页概览数值与 `/api/v1/kb/stats` 一致（5 库 / 437 节点 / 2631 边 / 0 未解析），全局图谱缩放实测 `0.373 → 0.391 → 0.409`。

## 2026-11-19（管理台：文档上传入队 + 图谱详情卡放大）

- `feat(web)`：知识库页新增「上传文档」（ADR-0006）：目标库下拉、多选/拖拽 `.md`/`.txt`/`.jsonl`（单批 ≤20）、逐文件校验与拒绝原因；提交后轮询 `GET /api/v1/kb/uploads/{batch_id}`（5s，`counts.queued=0` 即停），只展示「已入队 / 已提炼 / 失败 / 缺失」，不直接编辑节点。队列满（1013）与未配置 DATA_DIR（503/2001）在弹窗内呈现。
- `feat(web)`：`web/src/lib/api.ts` 新增 `uploadDocuments` / `uploadStatus`；`request()` 对 `FormData` 请求不再误设 `Content-Type: application/json`。
- `fix(web)`：图谱页（全局与单库）选中节点的详情卡从固定 `w-80`（320px）放大到 `min(92vw, 28rem)`，标题字号与 id/标签字号上调，长标题更易读。
- `fix(web)`：知识库概览的「最近更新」改为在库统计、最近节点列表与图谱节点三处取最大时间——`projects` 返回前或缓存较旧时，旧代码用未排序的 `nodes[0]` 兜底，日期会比下方「最近更新的节点」列表落后。
- 验证：`pnpm typecheck`、`pnpm build` 通过；ego-browser 实测上传弹窗（空选择禁用、空库提示、提交后终态显示「已提炼」）与图谱详情卡放大效果，标签页已关闭。后端真实链路由 export-memhub-4e 以 `worker --once` 验证：batch `10d8af13…`，+13 节点 / 11 边，cloudworld 变为 103 节点 / 591 边。

## 2026-11-19（worker：空响应重试并记录 stop_reason）

- `fix(worker)`：模型返回 200 但无 `text` 块时，此前直接按“非 5xx 不重试”抛错——真实跑上传验收时同一输入连续两次命中空响应，文件被记 2 次失败、逼近 3 次隔离线，而单独重放同一 prompt 又能正常返回。现在空内容按可重试处理，且错误信息带上 `stop_reason` 与 content 块类型，便于区分上游偶发空响应与 `max_tokens` 被 thinking 吃满。
- `test`：`tests/unit/test_llm.py` 新增空响应重试与错误信息用例（`httpx.MockTransport`，不 sleep）。
- 验证：上传批次 `10d8af13…`（cloudworld，`kb-upload-smoke.md`）`worker --once` 通过——`+13 new, 0 updated, 11 edges`，状态 `queued → processed`。

## 2026-11-19（上传：只接受已存在的知识库）

- `fix(kb)`：`POST /api/v1/kb/uploads` 校验 `project` 对应的 `<knowledge>/<project>/` 目录存在，不存在返回 404/`1011`。此前只校验 id 格式——拼错的 project 会被 worker 提炼时凭空建出一个空库目录，而管理台按真源一级目录枚举知识库，就会多出一个 0 节点的「幽灵库」。新增 `catalog.exists()` 轻量判断（不逐库扫节点）。
- `docs`：`kb-admin-api.md` §4.7 写明存在性校验与 404 语义。
- 验证：`pytest` 154 passed + 9 skipped（新增项目不存在与 LLM URL 归一用例）；`ruff check/format`、mypy strict（33 文件）、七个治理门禁全部通过。

## 2026-11-19（worker：LLM 端点兼容带 `/v1` 的 base_url）

- `fix(worker)`：`MEMHUB_LLM_BASE_URL` 以 `/v1` 结尾时，客户端此前会拼成 `/v1/v1/messages`，端点返回 404 且错误信息看起来像凭据问题。现在两种写法都归一为 `/v1/messages`；新增 `tests/unit/test_llm.py` 覆盖带/不带 `/v1` 与结尾斜杠四种形态。
- 实测：用真实配置跑 `worker --once` 一次成功（上传→提炼 16 节点/15 边，全部状态从 `queued` 变为 `processed`）；在此之前同一配置稳定 404。
- `docs`：`ENVIRONMENT.md` §3 注明 base_url 两种写法等价。

## 2026-11-19（知识库上传：文件直接进提炼队列）

- `feat(kb)`：新增 `POST /api/v1/kb/uploads`（multipart：`project` + `files`）与 `GET /api/v1/kb/uploads/{batch_id}`——文件落 `<DATA_DIR>/raw_store/kb-console/<project>/`（`source_type=docs`），复用 `memhub.queue.rawstore` 的内容寻址布局与配额，不经过采集协议（device token/游标/批次幂等都不适用）；批次清单写 `<DATA_DIR>/uploads/<batch_id>.json`；状态按 `processed_raw` / `pending_review` / `state/failures.json` / raw_store 逐文件推导。限制 `.md/.txt/.jsonl`、≤60000 字符、单批 ≤20 文件。
- `feat(contract)`：新增错误码 `1013 KB_QUEUE_FULL`（503，仅 KB 上传使用；`MEMHUB_QUEUE_MAX_BYTES` 超限）。
- `feat(cli)`：`memhub kb` 新增 `--data-dir`（缺省 `MEMHUB_DATA_DIR`），解析成绝对路径后交给 kb-api；未配置时上传接口返回 503，其余接口与启动不受影响。
- `docs`：`kb-admin-api.md` 升到 0.2，新增 §4.7 上传与 `1013`；`ENVIRONMENT.md` 的 `MEMHUB_DATA_DIR`、`MEMHUB_QUEUE_MAX_BYTES` 读取方加入 kb-api；architecture 的 kb-api 职责补上传入口。
- `test`：新增 `tests/contract/test_kb_uploads.py`，覆盖落盘路径、逐文件状态推导、部分拒绝/整批拒绝、项目 id 校验、配额 1013、未知批次 404 与未配置 DATA_DIR 的 503。
- 验证：`pytest` 149 passed + 9 skipped（PG 契约按开关跳过）；`ruff check/format`、mypy strict（33 文件）、七个治理门禁全部通过。

## 2026-11-19（分层：提炼队列落盘抽为 queue 模块）

- `refactor(queue)`：`ingest/rawstore.py` 整体移入 `src/memhub/queue/rawstore.py`——内容寻址布局、原子写、`tree_size`/`estimate_new_bytes`、`RawStoreQuota` 行为不变，`ingest/app.py` 与单元测试只改 import。原因：kb-api 的知识库上传要落同一个 raw_store，但不该让 `kb/` 依赖采集协议层（鉴权、游标、<200ms 约束）。
- `docs`：[architecture](architecture.md) 组件职责新增 queue（非独立进程，写入方 ingest-api/kb-api、读取方 worker），拓扑与目录同步；[DEVELOPMENT](guides/DEVELOPMENT.md) §2 分层树与归属表加入 `queue/`；ADR-0005 文件表注明 rawstore 已迁移。
- 验证：`pytest` 140 passed + 9 skipped（PG 契约按开关跳过）；`ruff check/format`、mypy strict（32 文件）、`check_async_io`、`check_no_raw_sql`、`check_document_format`、`check_document_ownership --all`、`check_adr_governance`、`check_agent_entrypoints_sync`、`check_env_example_keys` 全部通过。

## 2026-11-19（治理：Git 钩子覆盖 PowerShell）

- `fix(guard)`：`.claude/settings.json` 为 `PowerShell` 工具补注册同一守卫钩子——原先只注册 `Bash`，经 PowerShell 发起的 `git push` 会绕过；`guard-git-write.py` 补充识别 `git.exe`、`& git push` / `. git push` 调用运算符与大小写变体。
- 验证：钩子探针确认 PowerShell 形态的 `git status; git push`、`& git push`、`git.exe push`、`GIT push`、`powershell -Command "git push"` 返回 `ask`，`& git status`、`git.exe status` 放行；`python scripts/check_document_format.py` 与 `git diff --check` 通过。

## 2026-11-19（治理：接入评测仓的文档治理门禁）

- `feat(guard)`：把评测仓（`eval-platform-for-ai`）的文档治理脚本接入本仓，按本仓文档矩阵参数化，不改变既有正文语义：
  - `check_document_format.py` 换成同源实现（支持 `--staged`、H2 连续编号、ADR 手工编号与历史章节名检查），保留本仓对 `knowledge/`、`prompts/` 的排除；`ingest-api.md` 因有意从 §0 起编，不列入编号检查。
  - 新增 `check_document_ownership.py`（权威文档归属、实施历史不得进稳定文档、疑似密钥值）、`check_adr_governance.py`（索引、状态词、链接）、`check_agent_entrypoints_sync.py`、`check_commit_message.py`（禁止 `Co-Authored-By` 等工具署名行）。
- `docs`：按新门禁补齐权威文档元数据——`architecture.md`、`contracts/README.md` 与 5 份契约、`decisions/README.md`、`DEVELOPMENT.md` 增加「适用范围 / 不负责」；ADR-0005 状态行改为裸词 `accepted`，实现验证记录移入属性表的「验证」行。
- `chore(pre-commit)`：钩子扩为 ruff、基础检查（含 `check-yaml`、`mixed-line-ending`）、文档格式/归属（`--staged`）、ADR 治理、入口镜像、env 键集、mypy、禁手写 SQL、禁同步 I/O、提交信息检查（`commit-msg`）。
- 验证：`check_document_format.py`、`check_document_ownership.py --all`、`check_adr_governance.py`、`check_agent_entrypoints_sync.py`、`check_env_example_keys.py`、`check_no_raw_sql.py`、`check_async_io.py` 全部通过；`git diff --check` 通过。

## 2026-11-19（治理：Git 授权放开为仅限制远端操作）

- `docs`：根入口 `CLAUDE.md` / `AGENTS.md` §2 与 [DEVELOPMENT](guides/DEVELOPMENT.md) §6 的 Git 授权边界改为：本地写操作（提交、合并、变基、切换、worktree、分支与标签管理、清理等）默认授权，无需逐次确认；仅远端操作（`push`、`fetch`、`pull`、`clone`、修改 `remote`、推送标签、创建或更新 PR/release 等）需要负责人针对当前操作单独授权。本地不可逆操作执行前仍须确认不会丢弃其他会话未提交的改动。
- `feat(guard)`：新增 [.claude/hooks/guard-git-write.py](../.claude/hooks/guard-git-write.py) 并经 [.claude/settings.json](../.claude/settings.json) 注册 PreToolUse 钩子——只读命令与全部本地写操作放行；`push`、`fetch`、`pull`、`clone`、`ls-remote`、`remote` 改写、推送标签、`send-email`、`request-pull`、`lfs` 远端动作与 `archive --remote` 返回 `ask`。复合命令按 `&&`、`||`、`;`、`|` 逐段判定，`bash -c 'git push'` 旁路同样拦截；§5 的「不禁止 `Co-Authored-By`」当时保持不变，钩子不做署名拦截（§5 随后已改为禁止工具署名行，见同日治理条目）。
- 验证：`python scripts/check_document_format.py`、`git diff --check` 通过；`CLAUDE.md` 与 `AGENTS.md` 字节一致；钩子探针覆盖放行与拦截两组共 30 条命令，`commit`、`reset --hard`、`clean -fd`、`branch -D`、`worktree add`、`tag -d`、`lfs install`、`submodule status`、`stash` 等放行，`push`、`fetch`、`pull`、`remote show/set-url`、`lfs push`、`archive --remote`、`submodule update`、`send-email`、`request-pull`、`bash -c "git push"`、`git status && git push` 均返回 `ask`；`grep "git push"` 与 `python -c "print('git push')"` 不误拦。

## 2026-11-19（全仓 I/O 异步化：kb / worker / mcp / cli）

- 负责人收紧要求：**从数据库驱动到所有 I/O 一律 async，除特殊情况禁止同步函数**。在上一提交（数据访问层 ORM 化）基础上完成第二阶段，逐模块改造：
  - `refactor(kb)`：`store/query/catalog/manage/projection` 的文件 IO 全部改 `anyio.Path`（异步 `rglob`/`open`/`replace`/`stat`），写锁等待改 `anyio.sleep`，写锁文件按文本模式创建（修掉此前 bytes 写入文本句柄的潜在 TypeError）；git 提交走统一进程封装。
  - `refactor(kb-api)`：路由全部 `async def`；防抖重建用 `asyncio.Task`；静态文件存在性检查移到请求期 `await`（`StaticFiles(check_dir=False)` + 缺失时 503），启动期不再同步 stat；explorer 托管改用 `Popen` 封装，重启时在锁内先 terminate/kill 再拉起。
  - `feat(kb)`：新增 `kb/proc.py`——全仓唯一子进程入口，`subprocess.run/Popen` 放 `anyio.to_thread`。原因：Windows 上 psycopg 异步驱动要求 SelectorEventLoop，而 SelectorEventLoop 不支持 asyncio 子进程（实测 `NotImplementedError`）。
  - `refactor(worker)`：LLM 客户端换 `httpx.AsyncClient`；prompt 加载、raw 文件读写/移动、失败计数、隔离区与 `processed_raw` 裁剪全部异步；端点自检改 `asyncio.open_connection`；`run_forever` 的 sleep 可注入 async 实现。
  - `refactor(mcp)`：协议处理全 async；stdout 写入与 stdin `readline`（阻塞流）放 `anyio.to_thread`。
  - `refactor(ingest)`：`rawstore.save_batch/estimate_new_bytes/tree_size` 改原生 async（原子写 `anyio.Path`），`RawStoreQuota` 改 `anyio.Lock`；`/debug/sources` 与 `/healthz` 改 async；删除此前的 `asyncio.to_thread` 包装。
  - `refactor(cli)`：全部命令改 `async def`，入口一次 `asyncio.run(_dispatch())`；`api`/`kb` 用 `uvicorn.Server.serve()` 在同一事件循环内启动，explorer 走 `proc.run_command`，worker 退出前 `await client.aclose()`。
  - `test`：kb/query/catalog/manage/daemon/mcp/pipeline/rawstore 用例全 async 化；新增 async sleep 收集器与 `AsyncPath` 断言。
  - `feat(guard)`：新增 `scripts/check_async_io.py`（AST 扫描）并挂 pre-commit——禁止 `subprocess.*`、`os.walk/stat/utime`、`time.sleep`、`shutil.*`、内置 `open()`、`httpx.Client()`、`anyio.run_process/open_process`、`asyncio.create_subprocess_*`，以及同步 `Path(...)` 上的阻塞方法；白名单只有 `kb/proc.py`。附 `tests/unit/test_no_async_io.py` 自测。
- 验证：对临时 Docker PG 16 容器跑全量 **149 passed**（PG 契约真实执行，含并发重放）；未设 `MEMHUB_TEST_DB_URL` 时为 140 passed + 9 skipped；`ruff check/format`、mypy strict（31 文件）、`check_no_raw_sql.py`、`check_async_io.py` 均通过。

## 2026-11-19（数据访问层异步化：SQLAlchemy ORM + 禁手写 SQL）

- `refactor(ingest)`：按 ADR-0005 把数据访问层整体改为异步——`StateStore` 协议全部 `async def`，`PostgresStore` 换成 SQLAlchemy 2.0 async engine（`create_async_engine` + `async_sessionmaker`，`postgresql+psycopg`，复用现有 psycopg 3，不引入 asyncpg / asyncmy）。连接池随 engine 异步管理；`MEMHUB_DB_URL` 参数语义不变。
- `feat(ingest)`：新增 `models.py`（`devices`/`sources`/`file_cursors`/`batches`/`seen_shas` 的 `DeclarativeBase` 模型）。并发语义逐条用 Core/ORM 表达：advisory lock = `select(func.pg_advisory_xact_lock(func.hashtextextended(...)))`、行锁 = `with_for_update()`、去重 = `pg_insert(...).on_conflict_do_nothing().returning(...)`、游标 = `on_conflict_do_update`。表结构与 `MIGRATIONS` DDL 完全不变（不引入 Alembic）。
- `refactor(ingest)`：ingest 路由改 `async def`，`auth()` 与 store 调用 await；`raw_store` 落盘与配额扫描用 `asyncio.to_thread` 移出事件循环。`migrations.py` 的 `ensure_schema` 改接收 SQLAlchemy `Connection`（`exec_driver_sql`），DDL 列表冻结。
- `refactor(cli)`：`provision-device` / `purge-expired` / `_api` 改为局部 async 入口 + `asyncio.run`，命令语义与参数不变；Windows 上统一切 `WindowsSelectorEventLoopPolicy`（psycopg async 不支持 Proactor）。
- `feat(guard)`：新增 `scripts/check_no_raw_sql.py`——AST 扫描 `src/`，命中 `sqlalchemy.text(...)` 或传给 `execute/exec_driver_sql/scalar/scalars` 的 SQL 字符串即失败；唯一白名单 `migrations.py`（冻结基线），并挂到 pre-commit。附 `tests/unit/test_no_raw_sql.py` 自测。
- `test`：`tests/contract/test_state_store.py` 全 async，同一组场景参数化跑内存与 PG 实现，新增 `asyncio.gather` 同批重放用例；`tests/conftest.py` 在 Windows 下给 pytest-asyncio 提供 `SelectorEventLoop`。
- `deps`：新增 `sqlalchemy>=2.0.30,<2.1`（`postgres` extra）与 `pytest-asyncio`（`dev`）；`psycopg[binary,pool]` 保留。
- 验证：对临时 Docker PG 16 容器跑全量 **142 passed**（PG 契约真实执行，含并发重放）；未设 `MEMHUB_TEST_DB_URL` 时 PG 用例跳过、其余通过；`ruff check/format`、mypy strict（30 文件）、`python scripts/check_no_raw_sql.py` 均通过。
- 范围外（已被上条取代）：`kb-api`（`memhub kb`）无数据库访问，当时保持同步；markdown 文件 I/O 已在同日第二阶段全部异步化。

## 2026-11-19（治理：ego-lite 验收后关闭标签页）

- `docs`：根入口 `CLAUDE.md` / `AGENTS.md` §2 新增硬约束——使用 ego-lite（ego-browser）做页面验收后，关闭本次打开的所有标签页，避免占用浏览器资源、干扰后续会话或误认页面状态。
- 验证：`python scripts/check_document_format.py`、`python scripts/check_env_example_keys.py`、`git diff --check` 通过。

## 2026-11-19（知识库隔离导航 + 自绘图谱 + 旧 wiki 导入）

- `feat(kb)`：新增 `memhub.kb.catalog`——知识库（= 真源一级目录）成为一等公民：`GET/POST /api/v1/kb/projects`、`PATCH /api/v1/kb/projects/{project}`；显示名/描述存在 `<knowledge>/.kbs.json`，目录存在但未登记的库按目录名兜底。`GET /api/v1/kb/graph?project=` 直接读 markdown 真源返回**单库子图**（节点 + 解析后的边 + 度数 + 未解析边数），不依赖 `kg.json`。
- `feat(web)`：管理台改成知识库优先：`/` 是知识库列表（新建/编辑/卡片入口），`/kb/$project` 概览（规模、类型分布、最近更新），`/kb/$project/nodes` 只列本库节点，`/kb/$project/graph` 只画本库图谱。层级入口收敛在知识库页：侧栏**不再平铺各库**，只保留「全部知识库 / 全部节点 / 全局图谱」；旧 `/nodes`、`/graph` 仍然可用。
- `feat(web)`：知识库概览、节点列表、图谱和节点详情都加了面包屑与「返回」按钮（浏览器无历史时回落到上一级路径），深层跳转不再只能靠侧栏回一级。
- `fix(web)`：节点表格的 facet `filterFn` 签名写错（把 Row 当成被比较的值），从概览点「类型分布」会得到空列表；改为 `(row, columnId, filterValue)` 后按类型/层级筛选正常，页脚计数也改为表格实际筛选结果。节点详情的置信度空值判断从 `=== null` 改为 `== null`，不再显示 `undefined`。
- `feat(web)`：图谱页不再内联 semantica explorer，改用 Cytoscape + fCoSE 自绘：kind 配色、度数定大小、`≤60` 节点直接显示标签，更大的图只在枢纽/搜索命中/悬停邻域显示；支持类型过滤、隐藏废弃/孤立、搜索定位、适应画布与重新布局；点节点弹详情卡并跳转节点页。全局图谱按知识库分色。
- `fix(web)`：cytoscape 会注入未分层的 `.__________cytoscape_container{position:relative}`，优先级高于 Tailwind utilities；容器不能再靠 `absolute inset-0` 定位（会被压成 0 高、画布空白），改为 `size-full` 并用 `ResizeObserver` 同步尺寸。
- `feat(scripts)`：新增 `scripts/import_legacy_wiki.py`，把旧 `me/wiki`（Obsidian 风格）一次性迁移到新真源：type → kind 映射、description 前置引用块、`[[wikilinks]]` 解析成 `related_to` 边、来源记 `wiki`、层级 `canonical`，最后统一 git 提交；幂等（已存在即跳过）。
- 已导入 4 个库共 376 个节点、2620 条边：sdp-tag 206/1191、cloudworld 90/580、memory-hub 41/464、cloud-server 39/359；无法解析的 wiki 链接 176 条（只计数，不阻塞）。
- 验证：`pytest` 129 passed + 8 skipped；`ruff check/format`、mypy strict、`pnpm build` 通过；ego-browser 实测知识库列表 5 个库、sdp-tag 图谱 206 节点/1191 边可读、点节点出详情卡、全局图谱按库分簇。

## 2026-11-19（本地管理台：kb-api + 前端 + 图谱）

- 运行形态（用户决定）：**线上服务停掉，前后端全在本地，只有数据库连云端**，跑稳再上云。`deploy/README.md` §0 记录命令与 SSH 隧道约定。
- `feat(kb)`：新增 `memhub kb`（kb-api，`127.0.0.1:8701`，无鉴权、只绑回环）——节点列表/搜索/详情、新建、部分更新（`expected_revision` 内容寻址并发，冲突 409/`1010`）、废弃（tier+`superseded_by`+正文追加说明）、归档删除（`_trash/` + 移边 + 恢复）、出边整体替换、审计、统计、投影重建。写操作共用跨进程锁 `.memhub-write.lock`（120s 陈旧接管），成功后可选 `git` 提交。
- `feat(kb)`：投影重建防抖 1.5s；设置 `MEMHUB_KB_GRAPH_PORT` 时由 kb-api 托管 explorer 子进程、重建后重启（explorer 只在启动时读 `kg.json`）。
- `fix(kb)`：冷启动时 `/api/v1/kb/projection` 的节点/边数此前读的是进程内计数（恒为 0），改为直接读现有 `kg.json`。
- `fix(kb)`：投影节点 `content` 改放**标题**——semantica 把它当画布标签，此前放全文导致图上每个节点都是一段长文、互相压字；正文改为 `properties.body`（仍参与搜索）。
- `fix(kb)`：`git add` 会顺手把运行时锁文件 `.memhub-write.lock` 带进提交，已用 pathspec 排除；提交失败现在会打 warning（此前静默吞掉）。
- `feat(web)`：复用 DynamicFocusGroup/apps/web（底层 satnaing/shadcn-admin `e16c87f`，MIT）搭建管理台：概览、节点表格（服务端分页 + 类型/层级 facet + 全文过滤）、节点详情编辑/出边编辑/废弃/删除、回收站恢复、审计、图谱页（explorer iframe + 重建并刷新）。来源与许可见 `web/README.md`。
- `feat(contract)`：新增错误码 `1010 KB_CONFLICT / 1011 KB_NOT_FOUND / 1012 KB_INVALID`；契约文档 `docs/contracts/kb-admin-api.md`。
- 验证：122 passed + 8 skipped（PG 契约按开关跳过）；ruff / format / mypy strict 通过；`pnpm build` 通过；ego-browser 实测概览 48 节点/26 边、节点编辑保存往返（修订号变化、toast）、图谱页渲染并可见 about 边。

## 2026-11-19（上线当日回改）

- `fix(deploy)`：部署时由 peer 发现并修正的 5 处，已同步回仓库：① vhost `/api/v1/` 的 `proxy_pass` 必须带尾斜杠，否则前缀原样透传、采集路由全 404；② 补 `error_page 429 = @memhub_limited;`，否则限流信封是死 location；③ compose oauth2-proxy 的 `environment: ${VAR}` 会把 env_file 值覆盖成空串（`${}` 只查宿主 shell/.env），已删除映射、只留 env_file；④ v7.6.0 镜像 distroless，无 shell/wget，healthcheck 删除；⑤ `/portal` 实际目录为 `/var/www/portal/` 并补 `/portal` → `/portal/` 301。
- `feat(deploy)`：网关白名单按用户选择配置 `--github-user=tliliyuz`；v7.6.0 必须同时设 `--email-domain`（否则 invalid configuration），实际限制由 `github-user` 生效。
- 上线结果：四容器只监听 127.0.0.1（8700/8703/4180），ingest/explorer healthy；oauth2 4.6M / explorer 158M / ingest 62M / worker 34M；`/` 302 → GitHub authorize，`/oauth2/auth` 匿名 401，`/api/v1/healthz` 公网 404 / 本地 200，`/portal/` 200，purge 三行退出 0。

## 2026-11-19（oauth2-proxy 网关交付物）

- `feat(deploy)`：用户拍板 explorer 暴露用 **oauth2-proxy**（不做 basic auth 过渡）。compose 新增网关服务（v7.6.0 固定 tag，host 网络监听 127.0.0.1:4180 不发端口，128m，read_only+tmpfs+日志限流照容器标准）；凭据槽位只走 env_file，**凭据缺失启动失败是有意的**，日常 `up -d` 不含此服务。
- `feat(deploy)`：新增 `deploy/nginx/memhub.vhost.conf` 终稿草案——评审指出的现网缺失段已全部补齐（port-80 301、www server_name、安全头 always、TLS 1.2/1.3 加固、client_max_body_size 50m/20m、limit_req 全套与 429 JSON 信封、`/api/v1/healthz` 公网 404、/portal alias、upstream keepalive）。`location /` 双态切换用 `[ON]`/`[OFF]` 标注；**旧 sso 三个 location 显式移除**（后端已死，评审第 8 点）。limit_req zone 定义依赖 http 块既有配置，文件头有标注。
- 验证：`/api/v1/` 刻意不过认证网关——collector 是设备 token 自鉴权的哑管道，套人类 OAuth 会话破坏「采集端无状态」约束。

## 2026-11-19（processed_raw 裁剪）

- `fix(worker)`：`processed_raw/` 是 raw_store 的**完整副本**——文件处理成功后被移动过去，不受 `MEMHUB_QUEUE_MAX_BYTES` 约束。配额堵住了写入口，副本却会无限增长，磁盘照样能被写满（与上次事故同一条路径）。`purge-expired` 现在按「7 天保留期 + `MEMHUB_PROCESSED_MAX_BYTES`（默认 2 GiB）」双阈值、最旧优先裁剪，并回收空目录。
- 取舍：超期副本删除后无法用新 prompt 重跑旧会话；原始增量仍在 24h 批次窗口内、markdown 真源也保留溯源，故 7 天足够排查。需要长期归档时应单独做冷备，而不是让它默认长在数据盘上。
- 验证：95 passed + 8 skipped；新增用例覆盖按总量裁剪的最旧优先顺序与按 mtime 过期删除。

## 2026-11-19（raw_store 配额与隔离区清理）

- `feat(ingest)`：实现 `MEMHUB_QUEUE_MAX_BYTES`——它此前只写在文档里，代码从不读取，等于 raw_store 没有上限。现在 `/ingest/raw` 落盘前按「当前占用 + 本批新增」判断，超限返回 **1008/503**，采集端按契约降级；被拒批次一个字节都不落。新增量只算未落盘的 sha，**重放已收下的批次在满额时仍成功**，否则客户端会被永久卡死在一条已收下的数据上。用量缓存每 30 秒重扫一次纠偏（worker 夜间搬走文件后缓存会偏大），写盘失败则强制下次重扫。
- `feat(worker)`：实现 `pending_review/` 清理策略——`memhub purge-expired` 每天顺带删除超过 30 天（`--pending-review-days`）的隔离文件并回收空目录。隔离区此前只进不出，和 raw_store 一起会把磁盘预算吃穿。
- `docs(deploy)`：README 的「4 GiB raw_store 硬上限」改为「上限由 `MEMHUB_QUEUE_MAX_BYTES` 决定，`.env.example` 1 GiB，磁盘预算硬顶 4 GiB」——此前文档承诺的限额在代码里根本不存在。
- 验证：93 passed + 8 skipped（PG 契约仍按 `MEMHUB_TEST_DB_URL` 开关）；ruff / format / mypy strict 通过。新增用例覆盖超限 1008 不落盘、重放放行、非法值启动失败、隔离区按 mtime 清理与空目录回收。

## 2026-11-19（explorer 上容器）

- `feat(deploy)`：compose 增加 `explorer` 服务——复用 worker 镜像（需要 engine extra），`memhub serve --graph /var/lib/memhub/kb/kg.json --port 8703 --no-browser`，`HOME`/`TMPDIR` 指到 tmpfs，`restart: on-failure:5`。图谱不存在时 `serve` exit 2，因此**部署顺序是「先 rebuild 再起 explorer」**，写进 README §6/§7，并补了 nginx `/` 片段。
- `perf(deploy)`：按实测重排内存限额——ingest 384m（实测 59MB）、worker 640m（实测 155MB）、explorer 384m（实测 151MB），合计 1.4G，守住 1.5G 硬顶。
- 验证：本机 `--network=none` 构建 worker 镜像后以 `--read-only` + tmpfs + 非 root 999:987 起 explorer 容器，容器内 `GET /` 200、启动日志正常、`docker stats` 151.5MiB（Docker Desktop 的 host 网络不映射到 Windows 回环，因此从容器内探测）。

## 2026-11-19（迁移幂等性与启动建表）

- `fix(ingest)`：`ensure_schema` 用 `row[0]` 读版本，而连接池的行工厂是 `dict_row` → **第二次**迁移必 `KeyError`。空库首迁不读行，所以本地和首次部署都正常，线上 purge timer / `provision-device` / 容器重启才炸。现按行类型取 `version`；并补了 dict 行与 tuple 行两种假连接的回归测试（PG 测试本机默认跳过，这类问题只能靠它拦）。
- `fix(cli)`：`memhub api` 启动时显式 `migrate()`（有 `MEMHUB_DB_URL` 时）并打印结果，容器重启不再依赖「有人先跑过一次 purge」才有表。
- 验证：本地 Docker PG 16 上连续三次 `migrate()` → `['0001_state'] / [] / []`，`register_device` 正常；全量 **92 passed**（含此前默认跳过的 8 条 PG 契约，`MEMHUB_TEST_DB_URL` 指向临时库）。另补 dict/tuple 两种行工厂的假连接回归测试。

## 2026-11-19（关闭开放注册）

- `fix(ingest)`：`/devices/register` 此前在生产也是完全开放的——任何人都能自助领一枚合法 per-device token 往 raw_store 灌内容，最终污染知识库。契约 0.3 要求注册是**用户态操作**（桌面端持 `user_key`），用户体系还没落地；这一版用 `MEMHUB_PROVISION_TOKEN` 把口子关上：prod 缺该键拒绝启动，注册必须带 `Authorization: Bearer <provision_token>`，否则 401。prod 下 `device_id` 也改为必填（服务端自动生成只留给 dev stub）。
- `feat(cli)`：新增 `memhub provision-device --device-id --name --platform`——服务器上运维登记设备并把 token 打到标准输出（校验 UUID v4、要求 `MEMHUB_DB_URL` 与签发密钥）。token 不落文件，由调用方写进 OS 凭据库。
- 验证：82 passed + 8 skipped；`.env.example` 与 `ENVIRONMENT.md` 键集 17 键双向一致。

## 2026-11-19（抽取容错与毒文件隔离）

- `fix(worker)`：模型自造谓词（实测 `alternative_to`）此前会让**整篇文档**校验失败、留在队列无限重试且每轮重新付费。现在未知谓词收敛为 `related_to`（关系真实，只是用词越界），非法节点/边逐条丢弃并计数告警；只有「模型给了条目但一条都不合法」才判失败——那种情况说明契约跑偏，静默空结果会掩盖问题。
- `feat(worker)`：连续失败达上限（默认 3 次）的文件移入 `pending_review/`，原始字节保留待人工排查；失败计数落 `state/failures.json`，成功即清零。兑现了架构文档里「失败 3 次进 pending_review」的承诺，避免毒文件把队列永远染红。
- `fix(deploy)`：README 与 compose 对齐——容器是 `network_mode: host`，不存在 `127.0.0.1:8700:8700` 端口映射；内存限额改为 ingest 512m + worker 900m（实测 59MB / 155MB，留 5-8 倍余量），合计 1.4G 回到与评测中台约定的 1.5G 硬顶以内。
- `fix(deploy)`：worker 的 `restart` 由 `unless-stopped` 改为 `on-failure:5`。窗口外是常驻 sleep 不会退出，重启循环的真实来源是启动自检失败（缺配置 / LLM 不可达）——那种情况重试不会变好，连续 5 次后停住更利于发现。
- `docs(deploy)`：补 purge / rebuild 两个 timer 的完整 `docker run` 参数，逐项与 compose 对齐。
- 验证：79 passed + 8 skipped；本机真实链路复跑，此前必失败的那枚会话现产出 **54 节点 / 36 边**，被丢弃的 6 节点 / 4 边有明确计数日志。

## 2026-11-19（服务端端到端联调）

- 验证：按容器里的真实链路走了一遍——`/devices/register` → `/ingest/raw` 推送一枚真实 Claude Code 会话（190 KB）→ `raw_store` 内容寻址落盘 → `memhub worker --once` 调真实模型抽取 → `memhub project` 投影 → `memhub serve` explorer 页面渲染 **6 节点 / 4 边**（截图确认图谱画布、边标签、类型图例均正常）。
- 观察：第一枚会话 190 KB 但绝大多数事件是 `attachment` / `queue-operation` 等非对话类型，`render_jsonl` 只留下 127 字符，模型返回 0 节点属预期；换一枚对话密集的会话即抽出 6 节点。说明「渲染后为空」和「模型拒抽」在 `+0 new` 这个输出上无法区分——后续可在 worker 日志里补渲染字符数。
- `chore`：`.e2e/`（本地联调目录）加入 `.gitignore`。

## 2026-11-19（per-device token 与交付包）

- `feat(ingest)`：`/devices/register` 改为签发 HMAC per-device token（`v1.<device>.<mac>`），token 与设备绑定；冒用/篡改返回 401。`MEMHUB_ENV=prod` 下缺 `MEMHUB_DEVICE_TOKEN_SECRET` 拒绝启动，且 `MEMHUB_DEV_TOKEN` 被代码忽略（对齐 ENVIRONMENT.md 既有约定）。此前 prod 下 register 会把共享 token 发给任何人。
- `feat(cli)`：`memhub worker --dry-run`——校目录/配置后退出，供容器冒烟，不探 LLM。
- `chore(deploy)`：wheelhouse 改为 manylinux2014 + manylinux_2_28 并集下载并清理旧平台重复件；镜像内 `pip freeze` 生成 `deploy/lock-ingest.txt` / `lock-worker.txt`；`deploy/dist/MANIFEST.md` 提供每文件 sha256（164.8 MB 总计）。
- 验证：离线 `--network=none` 构建两镜像成功；`engine-import-ok`（numpy/pandas/scipy/sklearn/pyarrow/semantica.context）；worker dry-run 与 prod 拒绝启动均实测；74 passed + 8 skipped。

## 2026-11-19（api 入口与绑定地址防护）

- `feat(cli)`：新增 `memhub api`——ingest-api 的唯一启动入口。绑定地址按 `MEMHUB_HTTP_HOST` 优先、缺省 `127.0.0.1`；非回环地址必须 `--allow-non-loopback` 显式放行，否则 exit 2。host 网络部署下没有端口映射兜底，绑错即公网裸奔，因此把防护收进代码而非 compose 文本。
- `feat(deploy)`：Dockerfile.ingest 的 CMD 改为 `memhub api`；compose 增加 `stop_grace_period: 30s`，ingest 不再有 `ports:`，并注明 8700 必须是 `127.0.0.1:8700`。
- 验证：本机离线构建 ingest 镜像通过；容器冒烟 `/healthz` 正常、容器内 eth0 连 8700 被拒（只监听回环）；`MEMHUB_HTTP_HOST=0.0.0.0` 启动退出码 2。71 passed + 8 skipped，ruff / mypy strict 通过。

## 2026-11-19（worker 守护进程）

- `feat(worker)`：新增 `memhub worker`——raw_store → 抽取 → merge 进 markdown 真源的串行守护进程（池=1）。窗口门控 `--window 21:00-02:00`（本地时间、跨午夜），窗口外只休眠不占资源；`--once` 供 timer 单轮执行。
- `feat(worker)`：启动先做 LLM 端点 TCP 自检，不可达 exit 2（不进循环空转）；运行期失败按指数退避（间隔 ×2^n，封顶 30 分钟）；单文件失败留在原地下轮重试，进程退出码 1 表示部分失败、0 全部成功。
- `feat(worker)`：处理完成即原子移动到 `processed_raw/`（两个进程抢同一文件只有一个得手）；`.jsonl` 增量整段无法解析为事件时回退原文，不静默丢增量。
- 验证：75 passed（含 PG 契约），ruff / format / mypy strict 通过。

## 2026-11-19（raw_store 落盘）

- `feat(ingest)`：`/ingest/raw` 现在把原始增量真正落盘到 `<DATA_DIR>/raw_store/<device>/<source>/<sha[:2]>/<sha>.json`——内容寻址、原子写（tmp + replace）、重放/重复推送天然幂等；这是 worker 的唯一输入，此前只推进游标不落字节会丢数据。
- `feat(ingest)`：落盘在 `apply()` 之前，apply 校验失败只留无害的孤儿文件；反过来一旦落盘失败，重放将再也补不回来。
- `feat(ingest)`：`MEMHUB_ENV=prod` 而缺 `MEMHUB_DATA_DIR` 时拒绝启动（不静默丢数据）。
- 验证：58 passed + 8 PG skipped（设置 `MEMHUB_TEST_DB_URL` 后 66 passed），ruff / format / mypy strict 通过。

## 2026-11-19（fix：pre-commit 本地钩子依赖 venv）

- `fix(pre-commit)`：`mypy` 钩子 entry 由 `mypy src` 改为 `python -m mypy src`，`language: system` 下不再依赖 PATH 上单独暴露的 mypy 可执行文件。
- `docs`：`DEVELOPMENT.md` §3 类型命令同步为 `python -m mypy src`，并注明本地钩子依赖 PATH 上的 Python 与 venv 内的包，提交前需先激活虚拟环境。
- 验证：`python scripts/check_document_format.py`、`python scripts/check_env_example_keys.py`、`git diff --check` 通过。

## 2026-11-19（purge-expired CLI）

- `feat(cli)`：新增 `memhub purge-expired [--keep-hours N]`——读 `MEMHUB_DB_URL` 连 PG 执行批次 TTL 清理（默认保留 25h），先幂等 `migrate()` 再删，空库自愈；未设 DSN 时直接退出 0（内存实现无需清理）。供 systemd timer 单独调用，不拉起 API 进程。
- 验证：本地 Docker PG 冒烟通过（空库 0 条、DSN 缺省退出 0）；52 passed + 8 skipped，ruff / format / mypy strict 通过。注意：pytest 时误设 `MEMHUB_DB_URL` 会把 `build_store` 用例带去 PG，运行测试请勿设置该变量。

## 2026-11-19（治理基线：Agent 入口与 worktree 闭环）

- `docs`：新增根入口 `CLAUDE.md` 与 `AGENTS.md`（字节一致）——SDD 核心规范、门禁兜不住的硬约束、权威文档矩阵；此前仓库没有任何 Agent 自动加载入口。
- `docs`：`DEVELOPMENT.md` §6 由「分支」扩为「分支与 worktree 闭环」：所有代码修改在独立分支 + `.claude/worktree/<主题>/` worktree 中完成，禁止直接在 `main` 上实现（负责人显式授权的直提除外）；补充创建、清理命令与授权边界。
- `chore`：新增 `scripts/check_document_format.py`（H1、标题跳级、加粗伪标题、相对链接、镜像一致性；`knowledge/` 与 `prompts/` 为产出真源与抽取 profile，豁免结构规则）；`.pre-commit-config.yaml` 挂 `doc-format` 钩子。
- 验证：`python scripts/check_document_format.py` → 通过；`python scripts/check_env_example_keys.py` → 通过（16 键双向一致）；`git diff --check` → exit 0。pre-commit 已安装到 `.git/hooks`（本机）。

## 2026-11-19（运行态上 PostgreSQL）

- `feat(ingest)`：`StateStore` 协议 + PostgreSQL 实现（`PostgresStore`，psycopg 3 + 连接池）。批次重放用事务级 advisory lock，source 行 `FOR UPDATE`，seen_shas `ON CONFLICT DO NOTHING` 去重，整批单事务冲突全回滚；`MemoryStore` 同步改为整批原子。`MEMHUB_DB_URL` 有值即用 PG，留空退回内存实现（仅 dev）。迁移前向追加，版本记在 `schema_migrations`（ADR-0004）。
- `feat(ingest)`：新增 `purge_expired`（默认保留 25h），批次 TTL 清理待挂 systemd timer。
- `feat(ingest)`：`build_store()` 按环境选择实现；`register`/`cursor`/`raw`/`heartbeat` 路由全部只依赖 `StateStore` 协议。
- `chore(deps)`：新增 `postgres` extra（`psycopg[binary,pool]`）；dev extra 含同依赖供测试与 mypy。
- `docs`：ADR-0004（运行态放云上共享 PG 实例，database 隔离）；`ENVIRONMENT.md` 与 `.env.example` 以 `MEMHUB_DB_URL` 替换 `MEMHUB_DB_PATH`；architecture.md 拓扑图同步。
- 验证：本地 Docker PG 16 上契约测试 16/16（memory + postgres 双实现），全量 60 passed，ruff / ruff format / mypy strict 通过。

## 2026-11-18

- 新仓库建立；确立「无 Proxy」拓扑（ADR-0001）、markdown 真源（ADR-0002）、device token 作用域（ADR-0003）。
- 契约 v0.2：节点 schema、源注册表、采集 API、MCP 工具（`docs/contracts/`）。
- 工程骨架：`src/memhub/contract` 契约模型 + 契约测试；`pyproject.toml`（ruff/mypy strict）；环境键集治理脚本。
- 待办：ingest API、worker、kb 检索、MCP、部署文件、历史数据导入。

## 2026-11-18（追加）

- `feat(ingest)`：采集 API dev stub 可用（内存存储）——`/devices/register`、`/ingest/cursor`、`/ingest/raw`、`/ingest/heartbeat`；Bearer + 设备绑定、`source_rev` 重扫、1004 游标回退、24h 幂等重放、二进制拒收。契约测试 8 条。
- 本地联调：`MEMHUB_DEV_TOKEN=<任意值> PYTHONPATH=src .venv/Scripts/python -m uvicorn memhub.ingest.app:create_app --factory --port 8700`。

## 2026-11-18（最小闭环打通）

- `feat(worker)`：真实 Claude Code 会话（约 4 万字符）→ 40 个知识节点 / 26 条边写入 `knowledge/memhub/`；`kind=question` 缺 `status` 的崩溃已修并加回归测试。
- `feat(kb)`：markdown 真源 → semantica `ContextGraph` 投影（`kb/kg.json`，48 节点 / 26 边），边按完整 id 或唯一 slug 解析，未解析目标在报告中列出。
- `feat(cli)`：`serve` 自动为 explorer 子进程补齐 `PYTHONUTF8` / `PYTHONIOENCODING` / `SEMANTICA_ALLOW_ANONYMOUS`（显式环境变量优先），并打印页面地址；`engine` extra 补 `python-multipart`（explorer 缺它启动即失败）。
- 验证：`http://127.0.0.1:8011/` 页面可见 48 nodes · 26 edges 图谱（decision 10 / fact 17 / pitfall 7 / procedure 6 / preference 4 / entity 2 / question 2）。测试 24 passed，ruff/mypy strict 通过。
- 待办：SQLite 真存储与游标、value_filter、多会话批量、去重合并调参、MCP server、历史导入、云端部署。

## 2026-11-18（MCP 检索组）

- `feat(mcp)`：stdio 传输的 MCP 服务，暴露 `kb_search` / `kb_read` / `kb_related` / `kb_audit_list`；JSON-RPC 2.0 按行分帧，通知不回包，解析/参数/方法错误按 -32700 / -32602 / -32601 区分。
- `feat(kb)`：`kb/query.py` 实现检索组读操作——标题/标签/正文关键词打分（中文补二元组）、默认只看 canonical 并提示候选数、出入边各限 20 条、depth ≤2 邻接、审计问题现算（矛盾/断链/孤立/低置信/陈旧）。
- `feat(cli)`：新增 `memhub mcp --knowledge-dir`；stdio 强制 UTF-8（Windows 管道默认 cp936 会把中文协议写坏）。
- 验证：44 passed，ruff/格式/mypy strict 通过；真实知识库（48 节点）经子进程管道冒烟，中文标题原样返回。远程 `/mcp`（Streamable HTTP）未实现。
- 待办：SQLite 真存储与游标、value_filter、多会话批量、去重合并调参、历史导入、云端部署。
