# ADR-0005：数据访问层改为异步 I/O + SQLAlchemy ORM

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-19 |
| 验证 | 两阶段实现并验证（临时 PG 16 跑全量 149 passed） |
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
   文件 I/O（`raw_store` 落盘、quota 扫描）用 `asyncio.to_thread` 移出事件循环
   （第二阶段已改为原生 `anyio.Path` 异步实现，见下节）。
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
   第二阶段追加 `scripts/check_async_io.py` 覆盖全部同步 I/O（见下节）。
6. **CLI**：`memhub.cli.main` 里同步使用 `PostgresStore` 的路径改为局部 async 闭包 +
   `asyncio.run(...)`；不改变命令语义与参数。Windows 上 psycopg async 不能跑在
   `ProactorEventLoop`，CLI 入口统一调用 `_prepare_event_loop()` 切到
   `WindowsSelectorEventLoopPolicy`（测试侧由 `tests/conftest.py` 的
   `_asyncio_loop_factory` 提供 `SelectorEventLoop`）。

## 第二阶段：全仓 I/O 异步化（同日追加）

第一阶段（上面的决策 1–6）只覆盖了数据库访问路径。负责人随后把要求收紧为：
**「从数据库连接驱动到所有 IO 操作，一律用 async 的依赖与实现；增删改查用 SQLAlchemy；
除特殊情况禁止同步函数。」** 因此同日追加第二阶段，把「数据访问」扩大到「全部 I/O」。

实现范围与替代方案：

| 模块 | 改造 |
|:---|:---|
| `kb/store.py`、`query.py`、`catalog.py`、`manage.py`、`projection.py` | 文件系统全部改 `anyio.Path`（异步 `rglob`/`open`/`replace`/`stat`），写锁等待改 `anyio.sleep`，git 走进程封装；`frontmatter` 解析、打分、slug 等纯 CPU 函数保持同步 |
| `kb/api.py` | 路由全部 `async def`；防抖重建用 `asyncio.Task`；explorer 托管改 `proc.spawn`（Popen）；静态文件存在性检查改请求期 `await`（不再启动期同步 stat） |
| `kb/proc.py`（新增） | 全仓唯一的子进程入口。**Windows 的 SelectorEventLoop 不支持 asyncio 子进程**（`subprocess_exec` 直接 `NotImplementedError`，已实测），所以把 `subprocess.run/Popen` 放进 `anyio.to_thread`；调用方仍是 `await`，事件循环不阻塞 |
| `worker/llm.py`、`prompts.py`、`extract.py`、`merge.py`、`daemon.py` | `httpx.AsyncClient`；`anyio.Path` 读写/移动/清理；端点探活改 `asyncio.open_connection`；`time.sleep` 改 `asyncio.sleep`（可注入，测试用 async 收集器） |
| `mcp/server.py` | 协议处理全 async；stdout 写入与 stdin `readline`（阻塞流）放 `anyio.to_thread` |
| `ingest/rawstore.py`、`ingest/app.py` | 落盘、配额扫描、`/debug/sources` 全 async；`RawStoreQuota` 改 `anyio.Lock`；此前 `asyncio.to_thread` 包装删除。后续 `rawstore.py` 已移入 `queue/`（见同日 CHANGELOG 条目） |
| `cli/main.py` | 所有命令改 `async def`，入口一次 `_prepare_event_loop()` + `asyncio.run(_dispatch())`；`uvicorn.Server.serve()` 在同一循环内启动（不再嵌套 `asyncio.run`）；explorer 走 `proc.run_command` |

**同步例外清单**（不允许扩大，新增需在本 ADR 登记）：

1. `kb/proc.py` 里的 `subprocess.*`——Windows 事件循环限制，见上表；
2. `anyio.to_thread` 包装的第三方同步 API：semantica `save_to_file`、MCP stdio 的阻塞读写、
   进程调用本身；
3. `ingest/migrations.py` 的冻结 DDL 字符串（`exec_driver_sql`）；
4. 纯 CPU 函数（解析、渲染、打分、校验、slug 生成）与 `datetime`/`json` 等无 I/O 操作；
5. 测试夹具里的 `os.utime` 等时间戳设置（经 `anyio.to_thread` 调用）。

**门禁**：新增 `scripts/check_async_io.py`（AST 扫描 `src/`）并挂 pre-commit：命中
`subprocess.*`、`os.walk/stat/utime/...`、`time.sleep`、`shutil.*`、内置 `open()`、
`httpx.Client()`、`anyio.run_process/open_process`、`asyncio.create_subprocess_*`，
以及对同步 `Path(...)` 直接调用阻塞方法，即失败；白名单只有 `kb/proc.py`。
附 `tests/unit/test_no_async_io.py` 自测。

**实测**：对临时 Docker PG 16 容器跑全量 **149 passed**（PG 契约与并发用例真实执行）；
不设 `MEMHUB_TEST_DB_URL` 时 140 passed + 9 skipped；`ruff check/format`、mypy strict（31 文件）、
`check_no_raw_sql.py`、`check_async_io.py` 均通过。

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
   跑全量 142 passed（含 PG 契约并发用例）；第二阶段追加门禁自测后为 149 passed。
   不设 `MEMHUB_TEST_DB_URL` 时 PG 用例跳过，其余通过；ruff / format / mypy strict（30 文件）、
   门禁脚本均通过。

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
3. **~~`kb-api` 保持同步~~（已被第二阶段取代）**。第一阶段它只做 markdown 文件与 git 操作，
   不在「数据访问层 ORM 化」范围内；负责人收紧要求后，其路由、文件 I/O、子进程已在第二阶段
   全部异步化，不再另立 ADR。
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
- 全部 I/O 已异步化（第二阶段）：`kb/**`、`worker/**`、`mcp/**`、`cli/**`、`ingest/**`；
  新增同步 I/O 由 `scripts/check_async_io.py` 在提交前拦下。
- Windows 子进程唯一的同步出口是 `kb/proc.py`（线程内 `subprocess`）：SelectorEventLoop
  不支持 asyncio 子进程；Linux 生产环境不受影响，但为保持行为一致仍走同一封装。
- Windows 开发机必须用 `SelectorEventLoop`（psycopg async 不支持 Proactor）；
  生产 Linux 容器无此限制。
- ADR-0004 §3 的「psycopg 3 + 连接池」与 §6 的池参数被本 ADR 部分取代，其余结论继续有效。
