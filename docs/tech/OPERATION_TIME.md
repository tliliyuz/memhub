# 业务运行周期与时区

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-27 |
| 适用范围 | 业务时区、worker 提炼窗口与定时聚合的运行周期、幂等与重跑口径 |
| 不负责 | 通用时间存储与展示规则（见 [TIME_CONVENTIONS](TIME_CONVENTIONS.md)）；worker 队列契约（见 [architecture](architecture.md) 与 [ADR-0020](../decisions/ADR-0020-clickhouse-raw-store.md)） |

## 1. 业务时区

- 唯一业务时区是北京时间 `+08:00`，在 `governance.toml` 的 `[time] business_timezone` 声明；存储与接口仍一律使用 UTC 绝对时刻。
- worker 的 `--window` 由 `MEMHUB_WINDOW_TZ`（生产 `+08:00`）显式换算，不依赖容器 `TZ` 或镜像 tzdata（缺 zoneinfo 时会静默退回 UTC，线上踩过）。

## 2. 运行周期

| 任务 | 周期（+08:00） | 幂等与重跑 |
|:---|:---|:---|
| worker 提炼 | 跨午夜夜间窗口内串行轮询，窗口外只休眠不退出；生产窗口值见 `deploy/compose.yml` 的 `--window` | 队列主键 `(project, sha256)`，正文内容寻址；同一任务重复领取按租约回收 |
| 记忆聚合 | `memhub-memory-aggregate.timer`，每周一 `03:00`，`Persistent=true`（错过补跑） | 一次性 `docker run` 执行；只读写 `kb_*` 表并调用模型，不与 worker 窗口重叠 |

窗口与时区的实际取值以 `deploy/compose.yml` 与 `governance.toml` 为准；调整周期先改这两处，再同步本文。
