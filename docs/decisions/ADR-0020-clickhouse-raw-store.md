# ADR-0020 原始增量存 ClickHouse，提炼队列放 PostgreSQL

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-27 |
| 裁决人 | 负责人（经基础设施会话 cloud-server-0c 转述，本会话再次确认） |
| 关联 | [ingest-api.md](../contracts/ingest-api.md)、[ENVIRONMENT.md](../tech/ENVIRONMENT.md)、[architecture.md](../architecture.md)、ADR-0004、ADR-0013 |

## 背景

原始增量（会话原文、上传文档）一直落本机 `/var/lib/memhub/data/raw_store/<device>/<source>/<sha[:2]>/<sha>.json`，
worker 扫目录、处理后把文件搬到 `processed_raw/`，失败计数写在 `state/failures.json`。
这套文件队列有三个问题：

1. **原文只存腾讯云单机磁盘**：没有异地容灾，磁盘写满或机器故障即丢原文。
2. **worker 领取靠扫目录 + 原子 rename**：多实例语义弱，无法做「领取即占位、崩溃自动回收」的可靠队列。
3. **同一事实分散在文件系统、`seen_shas`、`state/failures.json`、`processed_raw/` 四处**，容易出现
   「文件在、去重记录不在」或「已处理、失败计数未清」的不一致。

百度云已就绪 ClickHouse（服务器 A，120.48.25.220）：库 `memhub_raw`、表 `raw_sessions`
（`ReplacingMergeTree(uploaded_at)`、`PARTITION BY toYYYYMM(uploaded_at)`、`ORDER BY (project, sha256)`、
`TTL toDateTime(uploaded_at)+INTERVAL 180 DAY DELETE`、`content String CODEC(ZSTD(3))`）。
访问通道为 nginx 8443 TLS（仅放行腾讯云 43.142.18.23、仅接受 `X-ClickHouse-User: memhub_rw`），
账号只有 `SELECT, INSERT`，没有 ALTER/DELETE（清理只能走本机 default 账号）。
实测上传约 0.6–0.8 MB/s，回读约 0.15 MB/s 且并发不提升，因此读写都必须开压缩。

## 决策

1. **原文真源改为 ClickHouse `memhub_raw.raw_sessions`**。ingest 收到批次后直接把正文写入该表；
   表按 `(project, sha256)` 去重（ReplacingMergeTree 保留最新 `uploaded_at`），180 天 TTL。
   客户端走 HTTP 8443 + 自签 CA 校验 + gzip（写入 `Content-Encoding: gzip`，读取
   `enable_http_compression=1` + `Accept-Encoding: gzip`）；不使用 native 协议驱动。
2. **提炼队列真源改为 PG 表 `ingest_queue`**，主键 `(project, sha256)`。字段：
   `sha256, device_id, project, source_id, batch_id, status, attempts, claimed_at, error,
   created_at, bytes, processed_at`。`status ∈ {queued, processing, processed, pending_review}`。
   worker 用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取，领取即写 `processing/claimed_at`；
   成功 → `processed`；永久拒绝或连续失败到上限 → `pending_review`；临时不可用 → 退回 `queued`。
   超过租约仍处于 `processing` 的行由下一轮自动回收为 `queued`。
3. **去重与失败语义收敛到队列**：
   - `seen_shas` 不再写入/读取，接受判重 = `ingest_queue` 主键冲突；旧表保留到生产切换后另行清理。
   - `state/failures.json` 删除，失败次数与原因进 `ingest_queue.attempts/error`。
   - `file_cursors`、`sources`、`batches` 语义不变（客户端游标与 24h 批次重放），与队列不重复。
   - 本机 `raw_store/`、`processed_raw/`、`pending_review/` 目录不再作为队列与真源使用。
4. **队列积压配额**：`MEMHUB_QUEUE_MAX_BYTES` 从「raw_store 磁盘上限」改为「待提炼内容字节上限」
   （按队列 `queued + processing` 的 `bytes` 求和）；`MEMHUB_PROCESSED_MAX_BYTES` 删除，
   `processed` 行按天数裁剪（行里不含正文，体积可忽略）。
5. **管理台上传改走 ingest 内部接口**：kb-api 不再直写本机文件，也不再持有运行态 DSN 或 CH 凭据。
   ingest 新增内部端点 `POST /internal/enqueue` 与 `GET /internal/queue/{batch_id}`，
   由 `MEMHUB_INTERNAL_TOKEN` 鉴权；kb-api 只持有该 token 与回环 ingest 地址。
6. **清理语义**：`DELETE /ingest/source/{source_id}` 只删除 PG 队列行（按状态计数）。
   CH 正文因账号无 ALTER/DELETE 权限，保留到 180 天 TTL；响应显式标记正文保留状态，
   不再声称清理原始字节。需要立即抹除时由运维用本机 default 账号执行。
7. **容灾方向未定**：CH 成为原文主存后需要 CH → 腾讯云/COS 的反向导出。本次不实现，
   在 `queue/content.py` 与本文档预留说明；在反向导出落地前，CH 是原文的单点。

## 备选与否决理由

- **继续用本机文件队列 + 定期备份到 COS**：不改 worker 领取语义，但无法解决「单机原文单点」与
  「多源状态不一致」，且备份恢复有 RPO 窗口。否决。
- **原文写 CH，同时保留 `seen_shas` 作为去重真源**：会留下两套「是否已收」的事实，
  跨源冲突时难以判定以哪套为准。否决，统一到 `ingest_queue`。
- **kb-api 直接持有运行态 DSN + CH 凭据写队列**：与「kb 用受限角色、只碰 `kb_*`」的密钥边界冲突。
  否决，改走 ingest 内部接口。
- **使用 clickhouse-connect 客户端**：需要新依赖；现有的 CH HTTP 接口 + 既有 `httpx` + 标准库 gzip
  已能满足读写与压缩需求。暂不引入新依赖。

## 后果

- 生产 `ingest` 与 `worker` 必须配置 `MEMHUB_DB_URL`（队列）与 `MEMHUB_CH_URL/USER/PASSWORD/CA`
  （原文）；缺任一启动失败，不退回本机文件。
- `memhub purge-expired` 不再清理 `pending_review/`、`processed_raw/` 文件，改为按天数裁剪队列行；
  批次重放窗口清理不变。
- 原文安全边界变化：原文离开腾讯云磁盘，进入百度云 CH；凭据只经 `/etc/memhub/env` 注入，
  文档与提交信息只写键名。
- 反向导出（CH → 腾讯云/COS）是后续独立任务；在它落地前，CH 是原文的单点存储。
