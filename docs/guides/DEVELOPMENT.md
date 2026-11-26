# DEVELOPMENT — 开发指南

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-25 |
| 适用范围 | 环境准备、目录门禁、命令、验证矩阵、提交粒度、分支与 worktree 闭环、Git 授权边界、编码约定 |
| 不负责 | 产品语义裁决、契约字段取值、系统拓扑（见 [architecture](../architecture.md) 与 [contracts](../contracts/README.md)） |

## 1. 环境准备

| 项 | 要求 |
|:---|:---|
| Python | 3.12+ |
| 包管理 | `uv`（优先）或 `venv + pip` |
| 容器 | Docker + Compose（部署与集成测试） |
| Git | 2.40+ |

```bash
python -m venv .venv
. .venv/Scripts/activate        # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,engine]"   # engine = 上传依赖 python-multipart（含投影下线后暂留的 semantica，依赖清理另案）；dev 已含 sqlalchemy/psycopg/alembic；验证 MCP HTTP 再追加 ,mcp-http
cp .env.example .env   # 再填 MEMHUB_KB_DB_URL（运行入口必填）、MEMHUB_TEST_DB_URL（测试用，指向 memhub_dev）
```

## 2. 目录分层与归属门禁

```text
src/memhub/
  contract/   跨端模型与枚举（对外字段的唯一实现）
  queue/      raw_store 落盘与配额（ingest 采集、kb 上传共用）
  ingest/     鉴权、游标、幂等、入队
  worker/     value_filter / extract / merge
  kb/         PG 存储（kb_*）、检索、管理台 API
  mcp/        MCP 工具
  cli/        运维命令
alembic/      kb_* 的 DDL 版本化（带外执行，门禁同样覆盖）
tests/
  unit/      纯逻辑
  contract/  契约模型验收
  fixtures/  固定样本（假 session、假 wiki 页）
docs/
scripts/      治理检查脚本
deploy/       compose / nginx / systemd / daemon.json
knowledge/    markdown 真源的一次性迁移源（迁移后删除，见 §9.1；运行时不再读取）
prompts/      各 source_type 的抽取 profile
```

| 要新增的内容 | 位置 | 不允许 |
|:---|:---|:---|
| 字段、枚举、校验 | `contract/` | 在 API 或 worker 里临时解析 JSON |
| 采集协议行为 | `ingest/` | 把提炼逻辑塞进 ingest（它必须 <200ms） |
| 队列落盘、用量与配额 | `queue/` | 在路由层复制落盘/配额逻辑，或让 kb 直接依赖 `ingest/` |
| 抽取 prompt | `prompts/` | 在 Python 里拼长 prompt 字符串 |
| 检索/写入 | `kb/` | MCP 层直接读文件 |
| 工具定义 | `mcp/` | 在工具函数里实现检索算法 |
| 运维命令 | `cli/` | 在命令里实现业务规则 |

新增顶层目录或改分层：先改 [architecture](../architecture.md)，再改本表。

治理门禁与评测仓同源（`scripts/` 下脚本 + pre-commit）：`check_document_format.py --staged`（结构、H2 编号、链接、入口镜像）、`check_document_ownership.py --staged`（权威文档归属、实施历史与密钥形态）、`check_adr_governance.py`（ADR 索引、状态词与编号唯一性）、`check_agent_entrypoints_sync.py`、`check_commit_message.py`（禁工具署名行）、`check_no_raw_sql.py`、`check_async_io.py`、`check_env_example_keys.py`。`knowledge/` 与 `prompts/` 不是治理文档，文档类检查自动排除。

## 3. 常用命令

| 目的 | 命令 |
|:---|:---|
| 测试 | `pytest` |
| 契约测试 | `pytest tests/contract` |
| PG 契约测试 | 在仓库根 `.env` 写入 `MEMHUB_TEST_DB_URL`（或只在当前 shell 导出），再 `pytest tests/contract`。测试入口在变量未设置时自动读取该键，显式环境变量优先，worktree 无需复制 `.env`；都拿不到时 PG 用例 skip，**skip 不计为通过**（ADR-0013 §10） |
| 检查 | `ruff check .` |
| 格式 | `ruff format --check .` |
| 类型 | `python -m mypy src` |
| 环境键集 | `python scripts/check_env_example_keys.py` |
| 文档链接与结构 | `python scripts/check_document_format.py` |
| 启动依赖 | `docker compose -f deploy/compose.yml up -d` |
| 本机运行 | `memhub --version` |

`MEMHUB_TEST_DB_URL` 的值只经 `.env` 或当前 shell 注入，不写进仓库、文档或提交信息。测试入口只从 `.env` 读这一个键，写进 `.env` 后直接 `pytest` 即可；若用 shell 导出，也只导出这一个键，不要整份 source 环境文件——那会顺带覆盖 `MEMHUB_DB_URL`、`PG*` 等运行态变量，测试结果不再可信。

本地钩子（`mypy`、`env-key-parity`、`doc-format`）使用 `language: system`，依赖 PATH 上的 Python 与 venv 内的包。提交前先激活虚拟环境（`. .venv/Scripts/activate` 或 PowerShell 的 `.venv\Scripts\Activate.ps1`），否则 `mypy` 会报 `Executable mypy not found`。

## 4. 验证矩阵

| 改动类型 | 至少执行 |
|:---|:---|
| 纯文档 | `git diff --check` + 环境键集（若动了 `.env.example`） |
| 契约字段 | 契约测试 + 文档同步 |
| ingest | 单元测试 + 契约测试 + 手工 curl 游标/推送 |
| worker/kb | 单元测试 + 固定样本回归（同一输入产出同一节点集） |
| kb 存储 / 迁移 / 契约夹具 | `MEMHUB_TEST_DB_URL` 已设置时的全量 `pytest`：PG 用例按 schema-per-test 建删 schema，未设置时整组 skip，视为**未验证** |
| MCP 工具或入口 | `pytest tests/unit/test_mcp_read_tools.py tests/contract/test_mcp_http.py`；HTTP 用例需安装 `.[dev,mcp-http]`，未装时整组跳过 |
| 部署文件 | `docker compose config` + 在临时目录验证 systemd unit 语法 |
| 治理脚本 | 全部脚本 + 在临时仓库验证能检出目标违规 |

未实际执行的项不得写成通过。

## 5. 提交粒度

- 一次提交只做一件事：一个行为、一次重构、一份文档。
- 格式：`<type>(<scope>): <中文摘要>`，`type ∈ feat|fix|docs|refactor|test|chore|perf`，摘要 ≤50 字。
- 不提交 `.env`、`data/`、`raw_store/`、真实会话内容。
- 提交信息只描述实际改动，**不加 `Co-Authored-By` 等工具署名行**；`scripts/check_commit_message.py` 在 `commit-msg` 阶段强制（与评测仓同源）。署名属于提交信息正文，不属于源码、文档或发布物。

## 6. 分支、Git 授权与 worktree 闭环

授权边界：

- Git 本地写操作默认授权，无需逐次确认——包括 `add`、`commit`、`merge`、`rebase`、`cherry-pick`、`revert`、`switch`、`checkout`、`restore`、`reset`、`clean`、`stash`、`worktree`、`branch`、`tag`、`config`、`rm`、`mv` 等；本地不可逆操作执行前仍须确认不会丢弃其他会话未提交的改动。
- 仅**远端操作**需要负责人针对当前操作明确授权：`push`、`fetch`、`pull`、`clone`、`ls-remote`、修改 `remote`、推送标签、`send-email`、`request-pull`、`lfs` 的远端动作，以及创建或更新 PR/release。本地操作的授权不覆盖任何远端操作。
- **机器化**：授权边界由 [.claude/hooks/guard-git-write.py](../../.claude/hooks/guard-git-write.py) 执行，经 [.claude/settings.json](../../.claude/settings.json) 注册——只读命令与全部本地写操作放行；远端子命令返回 `ask`，逐条确认。复合命令逐段判定，`git status && git push` 不会因前半段放行而整条通过。`Co-Authored-By` 等工具署名由 §5 的 `commit-msg` 门禁拦截；Git 授权钩子只判定远端操作，不做署名拦截。钩子不检查当前分支，worktree 闭环靠本节文本约束与自查执行。

worktree 闭环（硬约束）：

- `main` 是稳定分支，只有负责人明确允许后才能合入；发版只从 `main` 出，不从特性分支或 worktree 出。`dev` 是日常开发的集成分支，`dev` 合入 `main` 由负责人决定。
- **所有**代码修改（含功能、Bug 修复、文档与治理变更）都在从 `dev` 创建的独立分支 + 独立 worktree 中完成，禁止直接在 `main` 或 `dev` 上实现。例外：负责人对当次操作显式授权的直提（如小型仓库的急救修复）。
- worktree 必须由 `git worktree add .claude/worktree/<主题> -b <分支> dev` 创建；复制目录、只切分支不建 worktree 均不满足闭环。
- 完成后：验证 → 提交 → 合并回 `dev` → `git worktree remove` + `git branch -d` 清理，不长期停留在特性分支 → 在 [CHANGELOG](../CHANGELOG.md) 记录实际变化；涉及迁移的，同时记录迁移态六要素。

## 7. 依赖引入

新增依赖必须说明：用途与不可替代性、维护状态、体积、替代方案与被否理由、许可证。
固定版本下限与上限，不用浮动范围。

## 8. 编码约定

- 注释与文档中文；标识符、字段名英文。
- 公共函数与契约模型必须类型标注；`mypy strict`。
- 不用裸 `except`；异常转换为契约里的失败语义。
- 日志不得出现密钥、正文原文、token。
- 时间一律带时区 UTC。
- LLM 调用参数（模型、max_tokens）从配置读，不写死在函数里。

## 9. 端到端最小闭环（会话 → PG 真源 → 管理台）

前置：`.env` 里 `MEMHUB_KB_DB_URL` 指向一个可写的 `kb_*` 库（本地开发用 `memhub_dev` 的独立 schema，
生产用 `memhub_prod` 的 `kb`）。缺该键时每个运行入口都抛 `KbDsnMissing` 直接失败——知识没有文件/内存退路
（[ADR-0013](../decisions/ADR-0013-postgres-source-of-truth.md)）。

```bash
# 0) 建表：Alembic 用迁移角色带外执行（不在任何服务启动时跑）
MEMHUB_KB_MIGRATE_DB_URL=<迁移角色 DSN> alembic -c alembic.ini upgrade head
# 1) 抽取：会话 jsonl → kb_nodes / kb_edges（库必须已登记且未归档）
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main ingest \
  --path .scratch/sessions --profile sessions --project memhub --limit 3 --create-project
# 2) 管理台：http://127.0.0.1:8701/
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main kb \
  --web-dist web/dist --data-dir data
```

- `ingest` 只写提取出的节点，来源是本地文件；真源本身仍是库。`--create-project` 等价于先在管理台建库。
- 图谱与检索都直读 `kb_*` 表，不再生成或依赖任何文件投影。
- 页面首屏画布高度依赖视口，脚本化截图前先设置足够大的视口（如 1440×1000），否则画布可能塌成 1px。

### 9.1 一次性迁移（markdown → PostgreSQL）与归档恢复

```bash
# 目标库由 --dsn 或 MEMHUB_KB_DB_URL 决定。生产角色在数据库侧已把默认 search_path 设为 kb，
# 不传 --schema 即落 kb；--schema 只在测试/联调里覆盖 search_path（与 Alembic 同一口径）。
# 1) 只读统计：不写库、不删文件
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main migrate-kb \
  --knowledge-dir ./knowledge --dry-run
# 2) 写库：单事务、按 id / 边三元组 upsert，可重复运行
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main migrate-kb \
  --knowledge-dir ./knowledge --archives migrate
# 3) 逐节点、逐边比对内容哈希；不一致非 0 退出
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main migrate-kb \
  --knowledge-dir ./knowledge --archives migrate --verify-only
```

- `--archives migrate` 必须与第 2 步一致：迁移后 markdown 要删除，`kb_archives.snapshot` 是归档快照的唯一副本；
  默认的 `skip` 只统计不迁，会让归档库在库里缺快照。`--dry-run` 下两种取值都只统计。
- `--delete-source` 只接受与 `--verify-only` 同时使用，且校验通过后仍不执行删除（返回 3）：`pg_dump` 与
  `knowledge/` 打包备份、删除动作都由负责人在服务器上执行或明确授权（ADR-0013 §9）。
- 迁移前若 `knowledge/_kb_archives/pending.json` 存在，先用 `memhub recover-kb-archive --knowledge-dir ./knowledge`
  续做未完成的归档事务；它没解决就不要开始迁移（迁移会显式阻断）。

## 10. MCP 检索服务（stdio 与 HTTP）

```bash
# 直接跑：每行一条 JSON-RPC 2.0，stdout 只放协议，日志走 stderr
# 必须先配 MEMHUB_KB_DB_URL（运行入口强制 PG，缺失启动失败）；知识取自 kb_* 表，不再传 --knowledge-dir
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main mcp

# 挂到 Claude Code（本机当前目录）
claude mcp add memhub -- .venv/Scripts/python -m memhub.cli.main mcp
```

暴露四个检索工具和三个候选区写工具（契约见 [`mcp-tools.md`](../contracts/mcp-tools.md)）：
`kb_search`、`kb_read`、`kb_related`、`kb_audit_list`、`kb_write_candidate`、
`kb_update_candidate`、`kb_deprecate`。三个写工具都只作用于 `tier=candidate`；更新与废弃
必须带 `kb_read` 返回的 `revision` 作为 `expected_revision`。

分层：工具定义与入口在 `src/memhub/mcp/`——`tools.py` 共享实现与校验、`server.py` stdio 适配、
`http.py` HTTP 入口、`auth.py` 凭据鉴权；检索算法在 `src/memhub/kb/query.py`，受限读取与
路径校验在 `src/memhub/kb/reader.py`，候选写入在 `src/memhub/kb/candidates.py`。

### 10.1 HTTP 入口（可选，默认关闭）

```bash
python -m pip install -e ".[dev,mcp-http]"     # 官方 MCP Python SDK，只有 HTTP 入口需要
MEMHUB_MCP_GRANTS='[{"sha256":"<令牌的 SHA-256>","scope":"mcp:read",
  "expires_at":"<UTC ISO 时间>","projects":["<库 id>"]}]' \
  PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main kb --web-dist web/dist
# 客户端：POST http://127.0.0.1:8701/mcp，Authorization: Bearer <原始令牌>
```

- 由 kb-api 在精确 `/mcp` 提供无状态 Streamable HTTP（JSON 响应，不开 SSE 监听）。协议协商与
  报文解析交给官方 SDK，不复用 stdio 的 JSON-RPC 解析；未配置凭据时该路径直接 404，不落到 SPA。
- 每个请求重新计算授权范围：配置只存令牌的 SHA-256 摘要；作用域为 `mcp:read` 或 `mcp:write`，库名单由配置决定；
  浏览器 Cookie 与 `/ingest/*` 的 device token 都不授予 `/mcp` 权限。吊销 = 删摘要 + 重启。
- 同一进程同时只处理一个 POST，其余返回 429（`Retry-After: 1`）；请求体上限 16 KiB；带 `Origin`
  的请求一律 403，供纯机器客户端使用。
- 依赖：`mcp==2.3.0`（MIT，`modelcontextprotocol/python-sdk`；一并拉入 mcp-types、httpx2、
  sse-starlette、pyjwt[crypto] 等）。用它换掉自写协议层：Streamable HTTP 的会话、协商与错误语义
  由参考实现维护。未安装时只有启用 HTTP 才会报错，基础安装与 stdio 不受影响。
- 契约见 [`mcp-tools.md`](../contracts/mcp-tools.md) §4。

验收状态（2026-11-21）：

- 已验证：本地回环下，官方 SDK 客户端经 ASGI 传输完成握手、四工具发现、跨凭据库隔离、越权拒绝、
  并发 429、过期与吊销（见 CHANGELOG 2026-11-20）。该版本（`07d7bc8`）已合入 `main`。
- 已发布但未由开发侧复核：生产已部署该版本、公网 `/mcp` 已开通，依据是云主机运维会话的报告；
  nginx 路由属运维侧，本仓库测试不覆盖。
- 未验收：目标客户端经公网 `/mcp` 的端到端联调；容器内存预算。

stdio 编码固定 UTF-8（`serve()` 会 `reconfigure` 两个流）：Windows 管道默认 cp936，
不固定的话中文 JSON 到 agent 那边就是乱码。冒烟：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main mcp
```
