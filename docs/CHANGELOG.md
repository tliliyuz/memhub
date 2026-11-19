# CHANGELOG

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
