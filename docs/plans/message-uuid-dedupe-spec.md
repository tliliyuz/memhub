# 会话消息 uuid 去重实施规格

| 属性 | 值 |
|:---|:---|
| 状态 | specified |
| 日期 | 2026-11-26 |
| 承接 | [ADR-0017](../decisions/ADR-0017-session-message-uuid-dedupe.md) |
| 不负责 | 对外采集契约（[ingest-api](../contracts/ingest-api.md)）与知识节点 schema（[node-schema](../contracts/node-schema.md)） |

## 1. 范围与不变量

- 只作用于 `source_type=sessions` 且容器为 `.jsonl` 的批次；在 worker 渲染阶段按消息 `uuid` 过滤已见消息。
- `raw_store/` 原样保留，ingest 的 `sha256`、`duplicates`、游标、批次幂等与客户端契约全部不变。
- 没有 `uuid` 的行（非对话行、跨切片残行、非 JSONL 会话、wiki/docs）不参与消息级去重，按现状处理。
- 去重键 `(project, source_id, uuid)`；同键先成功抽取者胜，后到版本跳过。
- 不解决：fork 的整段上传带宽、raw 磁盘占用、跨项目复用、文档类源的重复。

## 2. 数据模型

运行态库（`MEMHUB_DB_URL`）新增前向迁移 `0002_seen_messages`：

```sql
CREATE TABLE IF NOT EXISTS seen_messages (
    project       text NOT NULL,
    source_id     text NOT NULL,
    uuid          text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project, source_id, uuid)
)
```

- 主键前缀 `(project, source_id)` 覆盖按库或按库+源清理，不再建额外索引。
- 不建外键：源被清理后仍保留已见记录，避免重新推送时重复抽取；清理走第 6 节的显式入口。
- 模型 `SeenMessage`（`ingest/models.py`）与 DDL 一一对应，只用于 ORM/Core 查询，不用 `create_all`。

## 3. 存储接口（`StateStore`）

新增三个方法，内存与 PG 实现语义一致：

- `async def seen_messages(project: str, source_id: str, uuids: Sequence[str]) -> set[str]`
  返回其中已见集合；空输入直接返回空集合，不落查询。PG 按 1000 个一批查询，避免参数上限。
- `async def mark_messages_seen(project: str, source_id: str, uuids: Sequence[str]) -> None`
  幂等写入（`ON CONFLICT DO NOTHING`），空输入不落写。
- `async def forget_messages(project: str, *, source_id: str | None = None) -> int`
  删除该库（可选限定源）的已见记录并返回行数；`source_id=None` 时清整库。

`MemoryStore` 用 `set[tuple[str, str, str]]` 承载，测试与 dev 联调用。

## 4. worker 流程

`render_session_blocks` 产出的 `SessionBlock` 增加 `message_id: str | None = None`：取 JSONL 事件的顶层 `uuid` 字符串；同一事件的多个文本块与后续分片继承同一 `message_id`；纯文本会话与解析失败行为 `None`。

`process_file` 在会话分支的顺序固定为：

1. 渲染全部块；
2. 若 `config.state` 非空，收集块上的非空 `message_id`，调用 `seen_messages`，过滤已见块；
3. 过滤后为空：不调用 LLM，返回“整片跳过”；
4. 再按 `max_input_chars` 截断（先去掉已见消息，把输入预算留给新消息）；
5. 抽取与 merge 成功后，对本轮实际发送的块的 `message_id` 调用 `mark_messages_seen`；
6. 抽取成功但没有节点，同样记账后返回；
7. 抽取或 merge 抛异常时不记账，保留 raw 文件供重试。

记账集合只含“实际进入 LLM 输入”的块：被截断掉的消息不记账，避免在未抽取的情况下永久跳过。

失败语义：

- 前置查询或记账失败视为运行态不可用：前置查询失败抛 `MessageIndexUnavailable`（新异常），`run_round` 捕获后**推迟本文件**（保留 raw、不增加失败次数、不调 LLM），日志 `[worker] defer: message_index_unavailable`；这与设备登记不可用的处理一致，覆盖“worker 先升级、ingest 尚未建表”的部署窗口。
- merge 已成功后记账失败不把文件判失败（否则会重复付费抽取）：记 ERROR 日志并照常完成文件，索引缺口由后续重推或显式重抽兜底。这是已知限制，写在第 8 节。

配置：`WorkerConfig` 新增 `state: StateStore | None = None`；CLI `_worker` 把已有的 `state` 一并传入。`MEMHUB_DB_URL` 缺省时 `state=None`，去重关闭，行为与现状完全一致（管理台上传与 dev 联调）。

`QueueTarget` 增加 `source_id` 字段（内部结构，不对外）。

## 5. 观测

- 单文件：过滤到已见消息时输出 `[worker] dedupe <path>: 已见 N 条，剩余 M 条`；整片命中时 `[worker] dedupe <path>: 全部消息已见过，跳过抽取`。只打计数与路径，不打正文。
- 轮次：`RoundReport` 新增 `deduped: int`（整片跳过抽取的文件数），`run_round` 汇总日志追加 `/<deduped> dedup`。
- `process_file` 返回值改为 `ProcessedFile(created, updated, edges, skipped_extraction: bool, filtered_messages: int)`；仅内部调用点与测试需要同步。

## 6. 重抽入口

新增 CLI 子命令：

```text
memhub forget-messages --project <kb-id> [--source <source-id>]
```

- 缺 `MEMHUB_DB_URL` 返回 2（配置错误）；存在时构造 `PostgresStore` 并先 `migrate()`（幂等，空库可自建表），再调用 `forget_messages`，打印删除行数。
- 允许通过 `args.state` 注入 `StateStore` 供测试使用。
- 只清索引，不动游标与 raw 文件；已见消息的原始字节若已被 `processed_raw` 裁剪，重抽需重新推送，命令输出中说明这一点。
- 用途：prompt 升级、抽取规则变化后的显式重抽；重扫（`source_rev` 提升）本身不重置索引。

## 7. 验收条件

| 编号 | 场景 | 预期 |
|:---|:---|:---|
| T1 | fork 复制行只改 `sessionId` | 渲染出的块带同一 `message_id`；分片与多文本块继承同一 id |
| T2 | 同一源先后推送父会话与 fork（旧消息 + 新增消息） | 第二次只把新消息送入 LLM；prompt 不含旧消息正文；索引补齐新消息 |
| T3 | 整片消息都已见 | 0 次 LLM 调用；`skipped_extraction=True`；文件照常移入 `processed_raw`；`RoundReport.deduped=1` |
| T4 | 抽取失败或 merge 失败 | 不写索引；下一轮重试仍调用 LLM |
| T5 | 同 `uuid` 不同 project | 不跳过（键含 project） |
| T6 | `state=None` | 行为与现状一致，消息全部抽取 |
| T7 | 存储契约（memory 与 PG） | 已见子集正确；重复 mark 幂等；forget 按库/库+源删除并返回行数；空输入不落写 |
| T8 | 迁移 | `0002_seen_messages` 只应用一次；`schema_migrations` 记录版本；重复迁移为空操作 |
| T9 | 无 `uuid` 行、跨片残行、`.txt` 会话 | 不参与去重、不报错，按现状渲染 |
| T10 | 前置查询失败（表缺失/DB 不可用） | 抛 `MessageIndexUnavailable`；`run_round` 推迟文件，不调 LLM、不计失败 |
| T11 | CLI `forget-messages` | 缺 DSN 返回 2；注入存储时删除并打印行数 |

## 8. 已知限制与迁移

- 索引写入在 merge 提交之后、独立事务：崩溃窗口内可能重复抽取一次；重复内容仍受 merge 的同正文与 slug 合并约束。
- merge 成功但记账失败时文件照常完成，索引会缺这一批 `uuid`，后续重推会再抽取一次；日志有 ERROR，可人工清理补救。
- 跨切片残行在现有实现里本就解析失败被跳过，本规格不改变该行为。
- 部署顺序：先升级并重启 ingest（启动时 `migrate()` 建表），再升级 worker；顺序反了 worker 会持续 `defer: message_index_unavailable`，不丢数据、不付费。
- 回滚：代码回退即可，`seen_messages` 表保留无害；确认不再使用后可手工 `DROP TABLE`。
- 迁移态：新增运行态表，无存量数据转换；`schema_migrations` 追加 `0002_seen_messages`；不涉及知识真源与 Alembic。
