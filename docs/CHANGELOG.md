# CHANGELOG

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
