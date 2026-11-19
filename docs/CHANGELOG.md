# CHANGELOG

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
