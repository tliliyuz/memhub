# DEVELOPMENT — 开发指南

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-19 |
| 适用范围 | 环境准备、目录门禁、命令、验证矩阵、提交粒度、分支与 worktree 闭环、Git 授权边界、编码约定 |

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
python -m pip install -e ".[dev,engine]"   # engine = semantica + explorer 依赖
cp .env.example .env
```

## 2. 目录分层与归属门禁

```text
src/memhub/
  contract/   跨端模型与枚举（对外字段的唯一实现）
  ingest/     鉴权、游标、幂等、raw_store、入队
  worker/     value_filter / extract / merge
  kb/         真源读写、检索、投影重建
  mcp/        MCP 工具
  cli/        运维命令
tests/
  unit/      纯逻辑
  contract/  契约模型验收
  fixtures/  固定样本（假 session、假 wiki 页）
docs/
scripts/      治理检查脚本
deploy/       compose / nginx / systemd / daemon.json
knowledge/    markdown 真源（git）
prompts/      各 source_type 的抽取 profile
```

| 要新增的内容 | 位置 | 不允许 |
|:---|:---|:---|
| 字段、枚举、校验 | `contract/` | 在 API 或 worker 里临时解析 JSON |
| 采集协议行为 | `ingest/` | 把提炼逻辑塞进 ingest（它必须 <200ms） |
| 抽取 prompt | `prompts/` | 在 Python 里拼长 prompt 字符串 |
| 检索/写入 | `kb/` | MCP 层直接读文件 |
| 工具定义 | `mcp/` | 在工具函数里实现检索算法 |
| 运维命令 | `cli/` | 在命令里实现业务规则 |

新增顶层目录或改分层：先改 [architecture](../architecture.md)，再改本表。

## 3. 常用命令

| 目的 | 命令 |
|:---|:---|
| 测试 | `pytest` |
| 契约测试 | `pytest tests/contract` |
| 检查 | `ruff check .` |
| 格式 | `ruff format --check .` |
| 类型 | `python -m mypy src` |
| 环境键集 | `python scripts/check_env_example_keys.py` |
| 文档链接与结构 | `python scripts/check_document_format.py` |
| 启动依赖 | `docker compose -f deploy/compose.yaml up -d` |
| 本机运行 | `memhub --version` |

本地钩子（`mypy`、`env-key-parity`、`doc-format`）使用 `language: system`，依赖 PATH 上的 Python 与 venv 内的包。提交前先激活虚拟环境（`. .venv/Scripts/activate` 或 PowerShell 的 `.venv\Scripts\Activate.ps1`），否则 `mypy` 会报 `Executable mypy not found`。

## 4. 验证矩阵

| 改动类型 | 至少执行 |
|:---|:---|
| 纯文档 | `git diff --check` + 环境键集（若动了 `.env.example`） |
| 契约字段 | 契约测试 + 文档同步 |
| ingest | 单元测试 + 契约测试 + 手工 curl 游标/推送 |
| worker/kb | 单元测试 + 固定样本回归（同一输入产出同一节点集） |
| 部署文件 | `docker compose config` + 在临时目录验证 systemd unit 语法 |
| 治理脚本 | 全部脚本 + 在临时仓库验证能检出目标违规 |

未实际执行的项不得写成通过。

## 5. 提交粒度

- 一次提交只做一件事：一个行为、一次重构、一份文档。
- 格式：`<type>(<scope>): <中文摘要>`，`type ∈ feat|fix|docs|refactor|test|chore|perf`，摘要 ≤50 字。
- 不提交 `.env`、`data/`、`raw_store/`、投影产物、真实会话内容。
- **有意未采用**「禁止 `Co-Authored-By` 签名行」的检查：本仓库的运行环境会给提交自动追加署名，加检查会与工具链冲突。署名只存在于 git 元数据，不进入源码、文档或发布物；对外发布物由 `deploy/` 与镜像构建产出，不含提交信息。

## 6. 分支、Git 授权与 worktree 闭环

授权边界：

- Git 本地写操作默认授权，无需逐次确认——包括 `add`、`commit`、`merge`、`rebase`、`cherry-pick`、`revert`、`switch`、`checkout`、`restore`、`reset`、`clean`、`stash`、`worktree`、`branch`、`tag`、`config`、`rm`、`mv` 等；本地不可逆操作执行前仍须确认不会丢弃其他会话未提交的改动。
- 仅**远端操作**需要负责人针对当前操作明确授权：`push`、`fetch`、`pull`、`clone`、`ls-remote`、修改 `remote`、推送标签、`send-email`、`request-pull`、`lfs` 的远端动作，以及创建或更新 PR/release。本地操作的授权不覆盖任何远端操作。
- 本仓未注册 Git 授权钩子，上述边界靠本节文本约束与自查执行。

worktree 闭环（硬约束）：

- **所有**代码修改（含功能、Bug 修复、文档与治理变更）都在独立分支 + 独立 worktree 中完成，禁止直接在 `main` 上实现。例外：负责人对当次操作显式授权的直提（如小型仓库的急救修复）。
- worktree 必须由 `git worktree add .claude/worktree/<主题> -b <分支>` 创建；复制目录、只切分支不建 worktree 均不满足闭环。
- 完成后：验证 → 提交 → 合并回 `main` → `git worktree remove` + `git branch -d` 清理 → 在 [CHANGELOG](../CHANGELOG.md) 记录实际变化；涉及迁移的，同时记录迁移态六要素。

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

## 9. 端到端最小闭环（会话 → 真源 → 图谱页）

```bash
# 1) 抽取：会话 jsonl → knowledge/<project>/<kind>/<slug>.md
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main ingest \
  --path .scratch/sessions --profile sessions --project memhub --limit 3
# 2) 投影：markdown 真源 → semantica ContextGraph
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main project --out kb/kg.json
# 3) 看图
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main serve --graph kb/kg.json --port 8011 --no-browser
#    → http://127.0.0.1:8011/ ，页面加载后点 “Open Semantica Explorer”
```

`serve` 只绑 `127.0.0.1`，并自动为子进程补齐 explorer 的运行环境：`PYTHONUTF8=1`、
`PYTHONIOENCODING=utf-8`（否则 Windows GBK 在启动日志的 `✓` 上崩）、
`SEMANTICA_ALLOW_ANONYMOUS=true`（否则 API 报 “Server is not configured for authentication”）。
已显式设置的同名环境变量优先，不会被覆盖。

产物不入库：`kb/kg.json` 是投影，随时可从真源重建；`knowledge/` 下的 markdown 才是真源。
页面首屏画布高度依赖视口，脚本化截图前先设置足够大的视口（如 1440×1000），否则画布可能塌成 1px。

## 10. MCP 检索服务（stdio）

```bash
# 直接跑：每行一条 JSON-RPC 2.0，stdout 只放协议，日志走 stderr
PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main mcp --knowledge-dir ./knowledge

# 挂到 Claude Code（本机当前目录）
claude mcp add memhub -- .venv/Scripts/python -m memhub.cli.main mcp --knowledge-dir ./knowledge
```

暴露检索组四个工具（契约见 [`mcp-tools.md`](../contracts/mcp-tools.md)）：
`kb_search`（默认只给 canonical，候选要显式 `tier="all"`）、`kb_read`（全文 ≤8KB + 出入边）、
`kb_related`（depth ≤2）、`kb_audit_list`（矛盾/断链/孤立/低置信/陈旧，现算）。

分层：工具定义与传输在 `src/memhub/mcp/server.py`，检索算法在 `src/memhub/kb/query.py`；
以后换 FTS/向量只改 `query.py`，工具形状不变。远程 `https://memhub.work/mcp`
（Streamable HTTP + device_token）复用 `handle_message`，当前未实现。

stdio 编码固定 UTF-8（`serve()` 会 `reconfigure` 两个流）：Windows 管道默认 cp936，
不固定的话中文 JSON 到 agent 那边就是乱码。冒烟：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | PYTHONPATH=src .venv/Scripts/python -m memhub.cli.main mcp --knowledge-dir ./knowledge
```
