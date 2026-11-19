# ADR-0005：数据访问层改为异步 I/O + SQLAlchemy ORM

| 属性 | 值 |
|:---|:---|
| 状态 | proposed（等待负责人确认） |
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
4. **迁移**：保留现有 `MIGRATIONS` 作为历史基线，用 Alembic 生成 `0001_state` 基线 revision
   （内容与现有 DDL 完全一致，不重写、不丢迁移）；启动时若发现旧库已有 `schema_migrations`
   但无 `alembic_version`，执行 `alembic stamp 0001` 完成衔接；新表结构变更从 0002 起走 Alembic。
5. **机械门禁**：新增 `scripts/check_no_raw_sql.py`（AST 扫描）并挂到 pre-commit：
   禁止 `sqlalchemy.text(...)`、传给 `execute()` 的 SQL 字符串字面量、`f"SELECT ..."` 拼接；
   允许 `func.*`/Core 构造与 Alembic 基线文件（白名单按文件+理由登记）。同时启用 ruff
   `S608`（hardcoded SQL）做第二道扫描。
6. **CLI**：`memhub.cli.main` 里同步使用 `PostgresStore` 的路径改为 `asyncio.run(...)` 包一层
   异步入口；不改变命令语义与参数。

## 改造范围（影响面清单）

| 文件 / 模块 | 变更 | 风险 |
|:---|:---|:---|
| `src/memhub/ingest/postgres.py` | 整体重写为 async engine + session + ORM 模型 | 高：并发语义必须逐条对齐 |
| `src/memhub/ingest/migrations.py` | DDL 冻结为 Alembic 基线；保留旧版本读取逻辑 | 中：旧库衔接 |
| `src/memhub/ingest/store.py` | `StateStore`、`MemoryStore` 改 async | 中：所有调用方跟着改 |
| `src/memhub/ingest/app.py` | 路由改 `async def`，`auth()` await，文件 I/O `to_thread` | 中：线程池行为变化 |
| `src/memhub/cli/main.py` | 3 处同步 store 调用改异步入口 | 低 |
| `tests/contract/test_state_store.py`、`test_ingest_api.py` | async 化 + 并发用例 | 中 |
| `.pre-commit-config.yaml`、`scripts/check_no_raw_sql.py` | 新增门禁 | 低 |
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
4. 迁移测试：空库建库 → 旧版本库（手工造 `schema_migrations` + 旧表）→ 启动后 stamp 成功、
   不重复执行 DDL。
5. 门禁自测：`check_no_raw_sql.py` 的通过/命中用例；ruff `S608` 在现有代码上应为 0 命中。
6. 收尾验证命令：`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`python scripts/check_no_raw_sql.py`；
   `pnpm build` 不受影响（前端无改动）。

## 回滚方案

- **数据层无回滚**：表结构不变（Alembic 基线等价于现有 DDL），不新增/删除列。
  任何一步失败都可以只回退代码提交，直接跑旧实现，数据库无需处理；`alembic_version`
  多出来的一行对旧代码无副作用。
- **分两次提交**：S1 = async 接口 + 路由 async 化（内部暂时用 `asyncio.to_thread` 包旧同步 store，
  行为等价，可单独回滚）；S2 = SQLAlchemy ORM 实现替换旧 psycopg 代码。S1 之后若出问题，
  回退 S2 即可回到「异步接口 + 同步实现」的已知可用状态。
- **开关**：`MEMHUB_STORE_IMPL=psycopg|sqlalchemy` 作为过渡期逃生口，默认 `sqlalchemy`，
  一个发布周期后删除开关与旧实现。
- **部署回滚**：只回退容器镜像 tag；数据库无 schema 变更，无需 restore。

## 待负责人裁决

1. Alembic 基线衔接方案（stamp 旧库）是否接受；还是保留自建迁移、只做 ORM（不做 Alembic）。
2. advisory lock 用 `func.pg_advisory_xact_lock` 表达是否满足「禁止手写 SQL」；
   若要求彻底无 SQL 片段，需新增 `batch_locks` 表改行锁（多一次 schema 迁移）。
3. `kb-api` 的同步文件 I/O 是否也在「异步 I/O」要求内——这会把 markdown 读写、git 提交
   一并异步化，范围显著扩大，建议单独立 ADR。
4. CLI 异步化随本次一起做，还是仅保留 `asyncio.run` 适配。

## 备选与否决理由

- **asyncpg**：性能更好，但要新增 native 依赖、独立 DSN 解析，且现有 psycopg 依赖无法复用；
  本项目写入负载小，否决。
- **保留手写 SQL、只把连接池换 async**：不满足「禁用 ORM 外手写 SQL」的指令要求，否决。
- **SQLModel**：更薄但类型/迁移生态弱于 SQLAlchemy 2.0，且维护节奏慢，否决。
- **整体换 asyncpg + 裸 SQL**：与指令相反，否决。

## 后果

- ingest 路径在单进程内不再占用线程池；高并发时行为更可预测。
- 新增依赖：`sqlalchemy>=2.0`、`alembic`（纯 Python，维护活跃，体积约数 MB）；
  psycopg 依赖保留。
- 迁移流程从「手写列表」变为 Alembic，后续 schema 变更需要生成 revision。
- ADR-0004 §3 的「psycopg 3 + 连接池」与 §6 的池参数被本 ADR 部分取代，其余结论继续有效。
