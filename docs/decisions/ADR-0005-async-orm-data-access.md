# ADR-0005：数据访问层改为异步 I/O + SQLAlchemy ORM

| 属性 | 值 |
|:---|:---|
| 状态 | accepted（2026-11-19 实现并验证） |
| 日期 | 2026-11-19 |
| 关联 | 部分取代 ADR-0004 §3（接入方式）、§6（连接数）；ADR-0002（markdown 真源不变） |

## 背景

负责人下达跨项目指令：**数据访问层必须改用异步 I/O + ORM，禁止手写 SQL**。

现状（核对结果）：

- `src/memhub/ingest/postgres.py`（267 行）用 `psycopg_pool.ConnectionPool` 同步连接池，
  SQL 全部手写（`INSERT ... ON CONFLICT`、`FOR UPDATE`、advisory lock、`Jsonb`）；
  `src/memhub/ingest/migrations.py` 是手写 DDL 列表 + 自建 `schema_migrations`。
- `src/memhub/ingest/app.py` 的路由全部是同步 `def`，依赖 FastAPI 线程池；
  `auth()` 与业务处理在路由里直接调同步 `StateStore`。
- `StateStore` 是同步 `Protocol`，`MemoryStore` 与 `PostgresStore` 两个实现。
- CLI（`memhub.cli.main` 的 `provision`/`purge-expired`/`rebuild` 等路径）同步构造并使用 `PostgresStore`。
- `src/memhub/kb/api.py` 只读写 markdown 文件与 git，**不访问数据库**——不在本 ADR 的 ORM 范围内
  （其文件 I/O 是否异步化见「待负责人裁决」第 3 条）。

## 决策

1. **ORM / 驱动**：SQLAlchemy 2.0 async（`create_async_engine` + `async_sessionmaker`），
   驱动用 `postgresql+psycopg`（复用现有 `psycopg[binary,pool]`，异步 dialect 由 psycopg 3 提供），
   不引入 asyncpg（多一个 native 依赖和 DSN 转换，收益仅是少量吞吐）。
2. **模型即 schema 来源**：为 `devices`、`sources`、`file_cursors`、`batches`、`seen_shas`
   定义 `DeclarativeBase` 模型；`schema_migrations` 保留，迁移历史不给改动。
   并发语义用 ORM/Core 构造表达，不写裸 SQL：
   - advisory lock：`select(func.pg_advisory_xact_lock(func.hashtextextended(...)))`；
   - 行锁：`select(...).with_for_update()`；
   - 去重：`postgresql.insert(...).on_conflict_do_nothing().returning(...)`。
3. **接口异步化**：`StateStore` 协议方法全部改为 `async def`；`MemoryStore` 提供平凡 async 实现
   （纯内存，不阻塞事件循环）；ingest 路由改 `async def`，经 `Depends` 注入 store/session。
   文件 I/O（`raw_store` 落盘、quota 扫描）用 `asyncio.to_thread` 移出事件循环。
4. **迁移（实现时修订）**：保留现有 `MIGRATIONS` 作为**冻结 DDL 基线**，由
   `ensure_schema(conn: sqlalchemy.engine.Connection)` 在启动时执行，版本记录仍写
   `schema_migrations`；本次**不引入 Alembic**——ORM 只替换数据访问方式，不改变表结构，
   引入 Alembic 会把「ORM 改造」和「迁移工具切换」两个风险绑在一起。Alembic 作为后续独立
   事项（届时用 `alembic stamp` 衔接旧库），新表结构变更在此之前继续走 `MIGRATIONS` 追加。
5. **机械门禁**：新增 `scripts/check_no_raw_sql.py`（AST 扫描）并挂到 pre-commit：
   禁止 `sqlalchemy.text(...)`、传给 `execute()`/`exec_driver_sql()` 的 SQL 字符串字面量、
   `f"SELECT ..."` 拼接；允许 `func.*`/Core 构造，唯一白名单是
   `src/memhub/ingest/migrations.py`（冻结基线，理由写在本 ADR）。ruff `S608`
   作为第二道扫描列为后续项，本次未启用（脚本门禁已覆盖运行时数据访问路径）。
6. **CLI**：`memhub.cli.main` 里同步使用 `PostgresStore` 的路径改为局部 async 闭包 +
   `asyncio.run(...)`；不改变命令语义与参数。Windows 上 psycopg async 不能跑在
   `ProactorEventLoop`，CLI 入口统一调用 `_prepare_event_loop()` 切到
   `WindowsSelectorEventLoopPolicy`（测试侧由 `tests/conftest.py` 的
   `_asyncio_loop_factory` 提供 `SelectorEventLoop`）。

## 改造范围（影响面清单）

| 文件 / 模块 | 变更 | 风险 |
|:---|:---|:---|
| `src/memhub/ingest/postgres.py` | 整体重写为 async engine + session + ORM 模型 | 高：并发语义必须逐条对齐 |
| `src/memhub/ingest/models.py`（新增） | `DeclarativeBase` + 5 张表模型；不调用 `create_all`，DDL 仍由 `migrations.py` 负责 | 低 |
| `src/memhub/ingest/migrations.py` | `ensure_schema` 改接收 SQLAlchemy `Connection`（`exec_driver_sql`），DDL 列表冻结不改 | 低 |
| `src/memhub/ingest/store.py` | `StateStore`、`MemoryStore` 改 async | 中：所有调用方跟着改 |
| `src/memhub/ingest/app.py` | 路由改 `async def`，`auth()` await，文件 I/O `to_thread` | 中：线程池行为变化 |
| `src/memhub/cli/main.py` | 3 处同步 store 调用改异步入口 | 低 |
| `tests/contract/test_state_store.py` | async 化 + 并发用例（`asyncio.gather` 重放） | 中 |
| `tests/conftest.py`（新增） | Windows 下 pytest-asyncio 使用 `SelectorEventLoop` | 低 |
| `.pre-commit-config.yaml`、`scripts/check_no_raw_sql.py`、`tests/unit/test_no_raw_sql.py` | 新增门禁 + 门禁自测 | 低 |
| `docs/contracts/ingest-api.md`、`docs/CHANGELOG.md` | 行为契约不变，只记录实现变更 | 低 |
| `MEMHUB_DB_URL` 连接参数 | 池大小语义从 psycopg 池换成 SQLAlchemy 池，连接数上限不变（ingest ≤3、worker ≤1） | 中：需在部署清单复核 |

不动：`knowledge/` 真源、`raw_store/`、API 契约、错误码、`kb-api` 的 markdown 读写。

## 测试策略（按 §1.1 先 RED 后 GREEN）

1. 先写 async 契约测试：同一组场景（注册、游标推进、重放幂等、游标冲突、去重、purge），
   参数化跑 `AsyncMemoryStore` 与 `AsyncPostgresStore`；目标行为缺失时确认 RED。
2. 并发用例：`asyncio.gather` 两个相同 `(device_id, batch_id)` 重放，断言只应用一次、
   两份结果的 `IngestResult` 一致；两个游标推进请求，断言不出现半写。
3. 路由黑盒测试：现有 `test_ingest_api.py` 改为 async 客户端，分别注入内存与 PG store，
   断言信封、错误码、状态码与改造前完全一致。
4. 迁移测试（实现时修订）：未引入 Alembic，改为「同一套 DDL 连跑两次幂等」
   （`tests/unit/test_migrations.py`，FakeConn 断言 `exec_driver_sql` 调用序列）；
   PG 契约用例为每个用例建独立 schema、跑完 DROP，验证真实 DDL 可在空库执行。
5. 门禁自测：`tests/unit/test_no_raw_sql.py` 覆盖 `text(...)`、SQL 字符串、f-string 命中
   与 ORM 表达式放行；ruff `S608` 未启用。
6. 收尾验证命令：`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`python scripts/check_no_raw_sql.py`；
   `pnpm build` 不受影响（前端无改动）。
7. 实测结果（2026-11-19）：对临时 Docker PG 16 容器（`memhub-pg-orm-test`，独立 schema）
   跑全量 142 passed（含 PG 契约并发用例）；不设 `MEMHUB_TEST_DB_URL` 时 PG 用例跳过，
   其余通过；ruff / format / mypy strict（30 文件）、门禁脚本均通过。

## 回滚方案

- **数据层无回滚**：表结构不变（DDL 基线原样保留），不新增/删除列。
  任何一步失败都可以只回退代码提交，直接跑旧实现，数据库无需处理。
- **单次提交（实现时修订）**：原计划拆 S1（异步接口 + `to_thread` 包旧实现）/
  S2（ORM 替换）两次提交，实际一次提交完成——契约测试对同一组场景同时跑内存与 PG 两种实现，
  等价性已由测试固定；再保留一个临时 `MEMHUB_STORE_IMPL` 开关只会多一条没人长期维护的分支。
  需要回退时直接 revert 该提交即可。
- **部署回滚**：只回退容器镜像 tag；数据库无 schema 变更，无需 restore。

## 待负责人裁决（实现时结论）

1. **保留自建迁移、不做 Alembic**。理由见决策 4：本次不改表结构；Alembic 单独做。
2. **advisory lock 用 `func.pg_advisory_xact_lock(func.hashtextextended(...))` 表达，接受**。
   它是 Core 函数构造，不是字符串 SQL；门禁脚本据此放行 `func.*`。若负责人要求彻底无函数调用，
   再改为 `batch_locks` 表行锁（需一次 schema 迁移）。
3. **`kb-api` 保持同步**。它只做 markdown 文件与 git 操作，没有数据库访问，不在「数据访问层
   ORM 化」范围内；其文件 I/O 是否线程化另立 ADR。
4. **CLI 只做 `asyncio.run` 适配**，不重写命令流程。

## 备选与否决理由

- **asyncpg**：性能更好，但要新增 native 依赖、独立 DSN 解析，且现有 psycopg 依赖无法复用；
  本项目写入负载小，否决。
- **保留手写 SQL、只把连接池换 async**：不满足「禁用 ORM 外手写 SQL」的指令要求，否决。
- **SQLModel**：更薄但类型/迁移生态弱于 SQLAlchemy 2.0，且维护节奏慢，否决。
- **整体换 asyncpg + 裸 SQL**：与指令相反，否决。

## 后果

- ingest 路径在单进程内不再占用线程池；高并发时行为更可预测。
- 新增依赖：`sqlalchemy>=2.0`（`postgres` extra），`pytest-asyncio`（`dev` extra）；
  未引入 alembic/asyncpg；`psycopg[binary,pool]` 依赖保留（池由 SQLAlchemy 接管）。
- 迁移流程保持「`MIGRATIONS` 列表 + `schema_migrations`」；Alembic 是后续独立事项。
- 禁止手写 SQL 由 `scripts/check_no_raw_sql.py` + pre-commit 守住；新增裸 SQL 会在提交前失败，
  例外只能在 ADR 登记后加入 `ALLOWED`。
- Windows 开发机必须用 `SelectorEventLoop`（psycopg async 不支持 Proactor）；
  生产 Linux 容器无此限制。
- ADR-0004 §3 的「psycopg 3 + 连接池」与 §6 的池参数被本 ADR 部分取代，其余结论继续有效。
