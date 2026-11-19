# ADR-0004：运行态放云上共享 PostgreSQL 实例

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-19 |
| 关联 | ADR-0002（markdown 真源）、docs/contracts/ingest-api.md |

## 背景

ingest-api 需要持久化运行态：设备注册、游标（device × source × path 的 offset）、
24h 批次幂等、按 (source, sha256) 的内容去重。原方案是 SQLite（本地文件）。
用户拍板：在云上搭一个共享 PostgreSQL 实例，memhub 与评测平台各用独立 database，
dev 库（`memhub_dev`）与生产库（`memhub_prod`）隔离。

## 决策

1. **实例共享、database 隔离**：一个 PG 16 实例，`memhub_prod` 给 memhub 生产，
   评测平台将来另开 database；dev/联调用本机库或云实例上的 `memhub_dev`。
   role 分开，互不持有对方权限。
2. **运行态 ≠ 知识**：本库只存"推到哪儿了、收过哪批、谁注册过"。
   知识真源仍是 `knowledge/**/*.md` + git（ADR-0002），原始增量是文件系统的
   `raw_store/`，投影可随时重建——本库丢失可从设备重推 + 投影重建恢复。
3. **接入方式**：`StateStore` 协议（`memhub.ingest.store`），生产实现
   `PostgresStore`（psycopg 3 + 连接池），dev 用 `MemoryStore`。
   `MEMHUB_DB_URL` 有值即用 PG，留空退回内存实现。
4. **并发语义**：批次重放用事务级 advisory lock
   （`pg_advisory_xact_lock(hashtextextended(device:batch))`）串行化；
   source 行 `FOR UPDATE` 保证游标推进串行；seen_shas 用
   `INSERT ... ON CONFLICT DO NOTHING RETURNING` 做去重；整批单事务，冲突全回滚。
5. **迁移前向追加**：版本记在 `schema_migrations`，无回滚脚本（运行态不值得）。
6. **容量约束**（与 cloud-server-86 对齐）：实例 `max_connections=60`，
   memhub 池 ingest 2+3、worker 1+1，≤7 连接；worker 单并发串行；
   批次 TTL 清理（25h）由 systemd timer 调 `purge_expired`，不用 pg_cron。

## 后果

- ingest-api 无状态化做成了协议层的事：任何 `StateStore` 实现都可插。
- 本地开发不再需要 SQLite 文件；没有 `MEMHUB_DB_URL` 时内存实现足够联调。
- PG 成为生产依赖（`pip install memhub[postgres]`），部署清单里多一个 native PG 16
  （`listen_addresses=localhost`、`pg_hba` 仅 local + 127.0.0.1 的 scram-sha-256）。
- 拒绝过的替代方案：SQLite（多进程并发与运维共享库的需求不符）、
  把 PG 当真源（违反 ADR-0002）、Redis（多一个常驻组件，内存预算放不下）。
