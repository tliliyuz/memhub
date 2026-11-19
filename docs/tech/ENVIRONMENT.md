# ENVIRONMENT — 配置与环境变量

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-18 |
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
| `MEMHUB_DATA_DIR` | 是 | — | ingest/worker | 启动失败 |
| `MEMHUB_KNOWLEDGE_DIR` | 是 | — | kb/worker | 不存在则启动失败（不自动创建真源目录） |
| `MEMHUB_DB_URL` | 否 | 空（退回内存态，仅 dev） | ingest | 格式 `postgresql://user@host:port/db`；生产必填，prod 下为空启动失败 |
| `MEMHUB_HTTP_HOST` | 否 | `127.0.0.1` | ingest | — |
| `MEMHUB_HTTP_PORT` | 否 | `8700` | ingest | 非法端口启动失败 |
| `MEMHUB_LLM_BASE_URL` | 是 | — | worker | 启动失败（worker 不降级为无模型运行） |
| `MEMHUB_LLM_API_KEY` | 是 | — | worker | 启动失败；日志中永不出现 |
| `MEMHUB_LLM_MODEL_FILTER` | 是 | — | worker/value_filter | 启动失败 |
| `MEMHUB_LLM_MODEL_EXTRACT` | 是 | — | worker/extract | 启动失败 |
| `MEMHUB_DEVICE_TOKEN_SECRET` | 是（prod） | — | ingest | prod 缺失启动失败；签发 `v1.<device>.<HMAC>` per-device token，轮换即令全部 token 失效 |
| `MEMHUB_PROVISION_TOKEN` | 是（prod） | — | ingest | prod 缺失启动失败；`/devices/register` 必须带 `Authorization: Bearer <provision_token>`，否则 401——用户体系未落地前用它关闭开放注册 |
| `MEMHUB_DEV_TOKEN` | 否 | 空 | ingest（dev） | 仅本地联调用的共享 token；`MEMHUB_ENV=prod` 时**被忽略**（代码层不读取） |
| `MEMHUB_QUEUE_MAX_BYTES` | 否 | `1073741824` | ingest | raw_store 用量上限；超限返回 `1008`（只按新增 sha 计，重放不受影响）；非法值启动失败 |
| `MEMHUB_PROCESSED_MAX_BYTES` | 否 | `2147483648` | purge-expired | `processed_raw/` 总量上限，配合 7 天保留期按最旧优先裁剪；非法值退出 2 |
| `MEMHUB_DISK_WARN_PCT` | 否 | `80` | disk-guard | 非法值启动失败 |
| `MEMHUB_GIT_REMOTE` | 否 | 空 | kb | 空则不自动 push |

## 3. 模型调用

- 走 Anthropic 协议（`POST {BASE_URL}/v1/messages`），`x-api-key` 头。
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
