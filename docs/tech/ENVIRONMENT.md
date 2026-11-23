# ENVIRONMENT — 配置与环境变量

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-21 |
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
| `MEMHUB_KNOWLEDGE_DIR` | 采集写入必需 | — | ingest / kb-api / worker | 三者必须指向同一真源。ingest 缺配置则不授予任何目标；配置后目录无法核验则返回通用服务错误。worker 缺配置且未传 `--knowledge-dir` 时退出 2；kb-api 的本地入口可传 `--knowledge-dir` |
| `MEMHUB_DB_URL` | 生产采集必需 | 空 | ingest / worker | 格式 `postgresql://user@host:port/db`；两者必须使用同一登记库。ingest 无 DSN 使用进程内状态；独立 worker 无 DSN 无法验证采集设备，保留采集队列等待验证，不影响管理台上传 |
| `MEMHUB_HTTP_HOST` | 否 | `127.0.0.1` | ingest | — |
| `MEMHUB_HTTP_PORT` | 否 | `8700` | ingest | 非法端口启动失败 |
| `MEMHUB_LLM_BASE_URL` | 是 | — | worker | 启动失败（worker 不降级为无模型运行） |
| `MEMHUB_LLM_API_KEY` | 是 | — | worker | 启动失败；日志中永不出现 |
| `MEMHUB_LLM_MODEL_FILTER` | 是 | — | worker/value_filter | 启动失败 |
| `MEMHUB_LLM_MODEL_EXTRACT` | 是 | — | worker/extract | 启动失败 |
| `MEMHUB_LLM_MAX_TOKENS` | 否 | `32000` | worker | 单次调用的输出预算（含 thinking）；非法值或非正数退出 2。8000 会被思考吃光、`stop_reason=max_tokens` 且无 text 块（线上首跑已踩） |
| `MEMHUB_WINDOW_TZ` | 否 | 空（系统本地） | worker | `--window` 的时区：`UTC` / `+08:00` / IANA 名；非法值退出 2。容器默认 UTC，不设时 `21:00-02:00` 实际跑在 05:00-10:00 CST（线上踩过）；生产用显式偏移 `+08:00`，不依赖镜像 tzdata |
| `MEMHUB_KB_API_URL` | 否 | `http://127.0.0.1:8701` | ingest | `/ingest/projects` 的同机 kb-api 上游：GET 取列表元数据后按授权和活动登记过滤，无授权时不查上游；POST 先查预授权才转发。上游不可用返回 `500/2001`；raw 的目标校验直接读本地策略和登记，不依赖此 URL |
| `MEMHUB_DEVICE_TOKEN_SECRET` | 是（prod） | — | ingest | prod 缺失启动失败；签发 `v1.<device>.<HMAC>` per-device token，轮换即令全部 token 失效 |
| `MEMHUB_PROVISION_TOKEN` | 是（prod） | — | ingest | prod 缺失启动失败；`/devices/register` 必须带 `Authorization: Bearer <provision_token>`，否则 401——用户体系未落地前用它关闭开放注册 |
| `MEMHUB_DEV_TOKEN` | 否 | 空 | ingest（dev） | 仅本地联调用的共享 token；`MEMHUB_ENV=prod` 时**被忽略**（代码层不读取） |
| `MEMHUB_QUEUE_MAX_BYTES` | 否 | `1073741824` | ingest / kb-api | raw_store 用量上限；ingest 超限返回 `1008`、kb 上传返回 `1013`（只按新增 sha 计，重放不受影响）；非法值启动失败 |
| `MEMHUB_INGEST_GRANTS_PATH` | 否 | `$MEMHUB_DATA_DIR/config/ingest-grants.json` | ingest / worker | 运维管理的非秘密精确设备→知识库授权；无文件、格式错误、非活动目标默认拒绝或暂不可验证，不支持通配符；真实权限不写入仓库或 token |
| `MEMHUB_PROCESSED_MAX_BYTES` | 否 | `2147483648` | purge-expired | `processed_raw/` 总量上限，配合 7 天保留期按最旧优先裁剪；非法值退出 2 |
| `MEMHUB_DISK_WARN_PCT` | 否 | `80` | disk-guard | 非法值启动失败 |
| `MEMHUB_GIT_REMOTE` | 否 | 空 | kb | 空则不自动 push |
| `MEMHUB_KB_GRAPH` | 否 | `kb/kg.json` | kb-api / explorer | 投影输出路径；不存在时 `/api/v1/kb/projection` 报 `stale=true` |
| `MEMHUB_KB_WEB_DIST` | 否 | 空 | kb-api | 留空只提供 API、不托管前端；目录里没有 `index.html` 时同样跳过静态托管 |
| `MEMHUB_KB_AUTO_REBUILD` | 否 | `1` | kb-api | `0/off/false` 关闭写后防抖重建，需手动 `POST /api/v1/kb/rebuild` |
| `MEMHUB_KB_GRAPH_PORT` | 否 | 空 | kb-api | 非空则托管 `python -m semantica.explorer` 子进程并在重建后重启；空则不自启（explorer 由外部管理） |
| `MEMHUB_MCP_GRANTS` | 否 | 空（`/mcp` 关闭） | kb-api | MCP HTTP 只读凭据，JSON 数组；每项含 `sha256`（令牌摘要，64 位小写十六进制）、`scope`（只接受 `mcp:read`）、`expires_at`（UTC）、`projects`（1–128 个库 id）。空或未设时 `/mcp` 一律 404 且不落到 SPA；配置非法（含重复摘要）启动失败；过期、缺失或不匹配的凭据返回 401。吊销 = 删除该条摘要并重启 kb-api；需安装 `memhub[mcp-http]`，否则启用时报错退出 |

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
| `MEMHUB_KNOWLEDGE_DIR` 只读 | 启动失败（避免"看起来在跑但不落盘"） |
| 磁盘水位超阈值 | disk-guard 告警 + 心跳附带；不自动删除任何数据 |
