# ENVIRONMENT — 配置与环境变量

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-26 |
| 适用范围 | 环境变量键集、默认值、读取方、失败语义 |
| 不负责 | 部署拓扑、契约字段 |

## 1. 规则

- 真实值只写 `.env`（已忽略），仓库里只有 `.env.example`（仅键名 + 安全默认）。
- 代码不得内置密钥；缺必填键时**启动失败**，不做静默降级。
- 键集由本文件 §2 定义，`scripts/check_env_example_keys.py` 双向校验。

## 2. 键集

| 键 | 必填 | 默认 | 读取方 | 缺失/非法时 |
|:---|:---|:---|:---|:---|
| `MEMHUB_ENV` | 否 | `dev` | 全栈 | 非 `dev/prod` 启动失败 |
| `MEMHUB_LOG_LEVEL` | 否 | `INFO` | 全栈 | 非法值启动失败 |
| `MEMHUB_DATA_DIR` | 是 | — | ingest/worker；kb-api（可选） | ingest/worker 缺失启动失败；kb-api 缺失时上传接口返回 503，其余接口正常（也可用 `memhub kb --data-dir` 指定） |
| `MEMHUB_KNOWLEDGE_DIR` | 否（仅迁移工具） | — | `memhub migrate-kb` / `recover-kb-archive`（一次性迁移源） | 运行入口（kb-api / MCP / worker / ingest / CLI）不再读取它；知识真源与登记状态一律取自 PG。留作 markdown 一次性迁移源与归档恢复源 |
| `MEMHUB_DB_URL` | 生产采集必需 | 空 | ingest / worker | 格式 `postgresql://user@host:port/db`；两者必须使用同一登记库。ingest 无 DSN 使用进程内状态；独立 worker 无 DSN 无法验证采集设备，保留采集队列等待验证，不影响管理台上传 |
| `MEMHUB_KB_DB_URL` | 所有运行入口必需（kb-api / MCP / worker / ingest / CLI） | 空 | 运行入口（`memhub.kb.session`） | 指向只对 `kb_*` 做 DML 的受限角色，库为 `memhub_prod`、`search_path` 固定 `kb`；DSN 必须自带口令（kb 容器只注入 `/etc/memhub/env.kb`，没有 `PGPASSWORD`）；缺失或为空抛 `KbDsnMissing`，**不回退文件/内存**。不得复用 `MEMHUB_DB_URL`（那是运行态角色，能碰运行态表与令牌摘要）。ingest 只用它读 `kb_projects` 校验采集目标 |
| `MEMHUB_KB_MIGRATE_DB_URL` | 迁移时必需 | 空 | Alembic（`alembic/env.py`） | 迁移角色，对 `kb_*` 有 DDL；`memhub migrate-kb` / 部署步骤带外执行，不在 kb 容器启动时跑。缺失抛 `KbDsnMissing`。运行态不读它。DSN 可写 `postgresql://`，入口按 psycopg 3 归一化为 `postgresql+psycopg://`（镜像里没有 psycopg2） |
| `MEMHUB_TEST_DB_URL` | 测试必需 | 空 | 契约与单元测试（`tests/conftest.py`） | 指向 `memhub_dev`（`memhub_dev_app`，无 CREATEDB，连接限额 8），每个用例建独立 schema。解析顺序：进程环境变量优先；未设置或为空时依次读仓库根 `.env` 与（worktree 场景）主 checkout 的 `.env`，只读这一个键，空值视同未设置。仍未获得时 PG 用例 skip，**skip 不计为通过** |
| `MEMHUB_HTTP_HOST` | 否 | `127.0.0.1` | ingest | — |
| `MEMHUB_HTTP_PORT` | 否 | `8700` | ingest | 非法端口启动失败 |
| `MEMHUB_LLM_BASE_URL` | 是 | — | worker | 启动失败（worker 不降级为无模型运行） |
| `MEMHUB_LLM_API_KEY` | 是 | — | worker | 启动失败；日志中永不出现 |
| `MEMHUB_LLM_MODEL_FILTER` | 是 | — | worker/value_filter | 启动失败 |
| `MEMHUB_LLM_MODEL_EXTRACT` | 是 | — | worker/extract | 启动失败 |
| `MEMHUB_LLM_MODEL_MEMORY` | 否 | 空（回退 `MEMHUB_LLM_MODEL_EXTRACT`） | `memory-aggregate` | 两者都为空时退出 2 |
| `MEMHUB_LLM_MAX_TOKENS` | 否 | `32000` | worker | 单次调用的输出预算（含 thinking）；非法值或非正数退出 2。8000 会被思考吃光、`stop_reason=max_tokens` 且无 text 块（线上首跑已踩） |
| `MEMHUB_WINDOW_TZ` | 否 | 空（系统本地） | worker | `--window` 的时区：`UTC` / `+08:00` / IANA 名；非法值退出 2。容器默认 UTC，不设时 `21:00-02:00` 实际跑在 05:00-10:00 CST（线上踩过）；生产用显式偏移 `+08:00`，不依赖镜像 tzdata |
| `MEMHUB_MEMORY_TOP_K` | 否 | `8` | worker / `memhub ingest` | 每次会话窗口最多注入的条目数；非 1–10 整数退出 2 |
| `MEMHUB_MEMORY_INJECT_CHARS` | 否 | `4000` | worker / `memhub ingest` | 记忆块字符预算；非正整数退出 2 |
| `MEMHUB_MEMORY_INJECT_DISABLED_PROJECTS` | 否 | 空 | worker / `memhub ingest` | 逗号分隔的库 id，命中则不注入；忽略空白项，不校验库是否存在 |
| `MEMHUB_KB_API_URL` | 否 | `http://127.0.0.1:8701` | ingest | `/ingest/projects` 只读列表的同机 kb-api 上游：GET 取列表元数据后按已登记且活动过滤；上游不可用返回 `500/2001`。raw 的目标校验直接读本地登记，不依赖此 URL；建库只在管理台 |
| `MEMHUB_DEVICE_TOKEN_SECRET` | 是（prod） | — | ingest | prod 缺失启动失败；签发 `v1.<device>.<HMAC>` per-device token，轮换即令全部 token 失效 |
| `MEMHUB_PROVISION_TOKEN` | 是（prod） | — | ingest | prod 缺失启动失败；为 `/devices/register` 与 `DELETE /ingest/source/{source_id}` 校验 Bearer 凭据；清理接口未配置该键时也返回 401（含 dev） |
| `MEMHUB_DEV_TOKEN` | 否 | 空 | ingest（dev） | 仅本地联调用的共享 token；`MEMHUB_ENV=prod` 时**被忽略**（代码层不读取） |
| `MEMHUB_QUEUE_MAX_BYTES` | 否 | `1073741824` | ingest / kb-api | raw_store 用量上限；ingest 超限返回 `1008`、kb 上传返回 `1013`（只按新增 sha 计，重放不受影响）；非法值启动失败 |
| `MEMHUB_PROCESSED_MAX_BYTES` | 否 | `2147483648` | purge-expired | `processed_raw/` 总量上限，配合 7 天保留期按最旧优先裁剪；非法值退出 2 |
| `MEMHUB_DISK_WARN_PCT` | 否 | `80` | disk-guard | 非法值启动失败 |
| `MEMHUB_GIT_REMOTE` | 否 | 空 | kb | 空则不自动 push |
| `MEMHUB_KB_WEB_DIST` | 否 | 空 | kb-api | 留空只提供 API、不托管前端；目录里没有 `index.html` 时同样跳过静态托管 |
| `MEMHUB_MCP_GRANTS` | 否 | 空（`/mcp` 关闭） | kb-api | MCP HTTP 凭据，JSON 数组；每项含 `sha256`（令牌摘要，64 位小写十六进制）、`scope`（`mcp:read` 或 `mcp:write`；`mcp:write` 隐含读）、`expires_at`（UTC）、`projects`（1–128 个库 id）与可选 `name`（展示名，1–64 字符；缺失时界面降级显示摘要前 12 位）。空或未设时 `/mcp` 一律 404 且不落到 SPA；配置非法（含重复摘要）启动失败；过期、缺失或不匹配的凭据返回 401。吊销 = 删除该条摘要并重启 kb-api；需安装 `memhub[mcp-http]`，否则启用时报错退出 |
| `MEMHUB_KB_TRACE_SPOOL` | 否 | `$MEMHUB_DATA_DIR/mcp_trace_spool.jsonl` | kb-api | MCP 调用轨迹的落库失败兜底文件（ADR-0015）。两者都未配置时 spool 关闭，仅记 ERROR 日志；路径不可写不阻断启动，但会在写失败时丢失该条记录。需要该目录对 kb 运行用户可写（容器内 `/var/lib/memhub`） |

## 3. 模型调用

- 走 Anthropic 协议（`POST {BASE_URL}/v1/messages`），`x-api-key` 头。`MEMHUB_LLM_BASE_URL` 写成 `https://host` 或 `https://host/v1` 都可以（客户端不会拼成 `/v1/v1/messages`）。
- worker 与 ingest 之间不共享模型凭据：ingest 不持有 `MEMHUB_LLM_*`。
- 不得把 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL` 直接当运行时配置使用——
  它们属于开发环境，生产配置必须是本文件 §2 的 `MEMHUB_*` 键。

## 4. 失败语义

| 情况 | 行为 |
|:---|:---|
| 必填键缺失 | 进程启动失败，退出码 2 |
| 模型不可用 | worker 重试 3 次后该文档进 `pending_review`；ingest 不受影响 |
| `MEMHUB_KB_DB_URL` 缺失 | 所有运行入口（kb-api / MCP / worker / ingest / CLI）启动失败（`KbDsnMissing`），不退回文件真源；ingest 不再读 `MEMHUB_KNOWLEDGE_DIR` 判目标 |
| 磁盘水位超阈值 | disk-guard 告警 + 心跳附带；不自动删除任何数据 |
