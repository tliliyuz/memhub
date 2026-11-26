# ADR-0006：管理台上传文档复用现有抽取管线

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-19 |
| 关联 | ADR-0002（markdown 真源）、ADR-0005（异步 I/O + 禁止手写 SQL） |

## 背景

管理台目前只有「结构化新建节点」：前端表单 → `POST /api/v1/kb/nodes`（JSON），没有文档上传能力。
运维和知识沉淀的真实需求是「把一篇文档交给系统，自动拆成多个带类型和关系的节点」，这与现有自动抽取链路完全一致：

```
collector 推送 → ingest-api 校验并落 raw_store
              → worker 扫描未处理 raw → value_filter → extract（LLM）
              → 自动判定 kind / entity_kind / 边 → merge 到 knowledge/<project>/
```

- `source_type` 现有 `sessions | wiki | docs`，其中 `docs` 已映射到 `wiki` 抽取 profile（`PROMPT_BY_SOURCE`）。
- worker 只认 raw JSON：`device_id / source_id / source_type / batch_id / path / sha256 / content`；
  `source_id` 在 merge 时就是知识库（project）。
- 自动写入一律 `tier=candidate`，人工确认后再升 canonical。（被 ADR-0014 修订：写入即 `canonical`，取消候选转正门槛。）

结论：上传不需要新的抽取实现，只需要把文档变成 worker 已经认识的 raw 文件。

## 决策

1. **入口**：kb-api 新增 `POST /api/v1/kb/uploads`，仅为本机管理台服务。
   不复用 `/api/v1/ingest/raw` 的 HTTP 语义——那是采集器接口，要求 device token、
   `batch_id` 幂等与 `source_rev` 游标；浏览器不持有设备令牌，也不该参与游标推进。
2. **复用落盘契约**：把 `ingest/rawstore.py` 整体抽到中性模块
   `src/memhub/queue/rawstore.py`（`batch_dir` / `save_batch` / `tree_size` /
   `estimate_new_bytes` / `RawStoreQuota`），ingest 与 kb 都依赖它，避免管理台
   绑定采集协议层；ingest 侧只改 import，行为零变化。分层变更先改
   `architecture.md` 再动代码，作为独立提交。kb-api 调用共享模块，产生与采集端
   **完全同形**的 raw 文件：
   - `device_id = "kb-console"`
   - `source_id = <project>`（必须先通过 catalog 校验知识库存在）
   - `source_type = "docs"`
   - `batch_id = uuid4()`，`path` 为上传文件名，`sha256` 为内容哈希
3. **幂等**：内容寻址天然去重——同一文档重复上传只落一个 raw 文件，不会重复提炼。
   MVP 不提供「强制重抽」；需要重抽时由运维把文件从 `processed_raw/` 移回 `raw_store/`。
4. **校验与限制**（全部在落盘前完成）：
   - 只接受纯文本：`.md` / `.txt` / `.jsonl`；含 `\x00`、非 UTF-8 一律拒绝。
     拒绝原因枚举：`unsupported_type` / `not_utf8` / `empty` / `too_large` /
     `invalid_name`。
   - 单文件 ≤ 60,000 字符（worker `max_input_chars` 当前值），超出直接拒绝，
     不静默截断；单次请求 ≤ 20 个文件。
   - 队列配额沿用 `MEMHUB_QUEUE_MAX_BYTES`，超限返回 503，不落半批。
5. **状态查询**：kb-api 在 `<DATA_DIR>/uploads/<batch_id>.json` 记录清单
   （文件名、sha256、相对 raw 路径），`GET /api/v1/kb/uploads/{batch_id}` 逐文件推导：
   1. `processed_raw/<relative>` 存在 → `processed`
   2. `pending_review/<relative>` 存在 → `failed`
   3. `state/failures.json[relative]` 有计数 → `failed`（附 `attempts`）
   4. `raw_store/<relative>` 存在 → `queued`
   5. 都不存在 → `missing`（清单有记录但文件已不在，提示重传）

   一批中部分 processed、部分 queued 是常态；worker 只在窗口期搬运，白天长时间
   `queued` 属于正常排队，不是失败。清单只用于查询，不参与 worker 处理；`uploads/`
   不在 `raw_store/` 内，不会被 `iter_pending` 误提炼。
6. **异步 I/O**：按 ADR-0005，路由与文件读写全部 async（anyio / `to_thread`），
   不引入同步文件操作，不写裸 SQL（本功能无数据库访问）。
7. **溯源**：MVP 复用 `source_type=docs`，节点 frontmatter 的 `source.type` 仍是 `wiki`。
   新增 `upload` 枚举会让契约与 worker 映射同时变更，单独立项再做。
8. **前端**（归 memhub-ca）：知识库页增加「上传文档」入口，支持多选与拖拽，
   选择目标知识库，提交后轮询批次状态；结果只展示「已入队 / 已提炼 / 失败」，
   不直接编辑节点内容。
9. **data-dir 与配额**：`memhub kb` 新增 `--data-dir`（缺省读 `MEMHUB_DATA_DIR`）；
   部署上 kb-api / ingest-api / worker 必须共享同一 DATA_DIR。`RawStoreQuota` 是
   进程内缓存（30s 重扫纠正），kb-api 与 ingest-api 并发放行时容忍约一个刷新窗口的
   短暂超限，不引入跨进程文件锁。

## 接口规格（草案）

```http
POST /api/v1/kb/uploads
Content-Type: multipart/form-data

project: <knowledge base id>
files:   <一个或多个文本文件>
```

成功 201：

```json
{
  "batch_id": "8f0c…",
  "project": "memhub",
  "accepted": [{"name": "runbook.md", "sha256": "…", "chars": 1820}],
  "rejected": [{"name": "logo.png", "reason": "unsupported_type"}],
  "queued": true
}
```

- 全部文件被拒 → 422 / `1012 KB_INVALID`，`data.rejected` 给出逐文件原因。
- 队列满 → 503 / `1013 KB_QUEUE_FULL`（`data:{used, limit, incoming}`），登记在
  kb-admin 自己的错误码区间（1010–1013 / 2001），不复用采集侧的 `1008`。
- 知识库不存在 → 404 / `1011 KB_NOT_FOUND`。
- 未配置 `MEMHUB_DATA_DIR` → 503 / `2001`，其余 kb-api 接口不受影响。

```http
GET /api/v1/kb/uploads/{batch_id}
```

```json
{
  "batch_id": "8f0c…",
  "project": "memhub",
  "created_at": "2026-11-19T09:00:00+00:00",
  "total": 2,
  "counts": {"queued": 1, "processed": 1, "failed": 0, "missing": 0},
  "files": [
    {"name": "runbook.md", "sha256": "…", "status": "processed"},
    {"name": "notes.txt", "sha256": "…", "status": "queued"}
  ]
}
```

`status ∈ queued | processed | failed | missing`；`missing` 表示清单有记录但三处
路径都不存在（人工清理或磁盘异常），按失败提示重传；`attempts` 只在重试失败时出现。

## 改造范围（影响面清单）

| 文件 / 模块 | 变更 | 归属 |
|:---|:---|:---|
| `src/memhub/queue/rawstore.py`（新） | 从 ingest 抽出的共享落盘与配额 | export-memhub-4e |
| `src/memhub/ingest/rawstore.py` | 改为引用共享模块，行为不变 | export-memhub-4e |
| `src/memhub/kb/api.py` | 新增上传与状态路由（async） | export-memhub-4e |
| `src/memhub/kb/uploads.py` | 校验、payload 组装、清单读写 | export-memhub-4e |
| `src/memhub/cli/main.py` | `kb` 子命令新增 `--data-dir` | export-memhub-4e |
| `tests/contract/test_kb_uploads.py` | 契约测试（校验、去重、配额、状态） | export-memhub-4e |
| `docs/architecture.md` | 分层图与组件归属补 `queue` 模块 | export-memhub-4e |
| `docs/tech/ENVIRONMENT.md` | `MEMHUB_DATA_DIR` 读取方增加 kb-api | 实现方 |
| `docs/contracts/kb-admin-api.md` | 新增 §4.7 上传接口与 `1013` 错误码 | export-memhub-4e |
| `web/src/lib/api.ts`、知识库页 | 上传弹窗、批次轮询 | memhub-ca |
| `docs/CHANGELOG.md` | 实现完成后追加 | 实现方 |

不动：worker 抽取逻辑、prompts、node schema、ingest 采集契约、`knowledge/` 直写路径。

## 测试策略（先 RED 后 GREEN）

1. 契约测试：二进制/超长/空文件被拒；知识库不存在 404；正常上传返回 201 且 raw 文件字段与采集端一致。
2. 幂等：同一内容上传两次，raw 目录只有一个文件，状态均为 queued。
3. 配额：把 `MEMHUB_QUEUE_MAX_BYTES` 设小，上传返回 503 且不落半批。
4. 端到端（mock LLM）：上传 → worker `process_file` → 临时 `knowledge/` 出现带 frontmatter 的节点，`source.type=wiki`。
5. 前端：上传弹窗的校验提示与状态轮询（组件测试或 ego-browser 手工验收，验收后关闭标签页）。
6. 收尾：`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`pnpm build`。

## 回滚

- 路由为纯新增，raw 文件与现有采集数据同构；回滚代码即可，已入队文件仍会被 worker 正常提炼。
- 清单文件与 `processed_raw` 均可安全删除，不影响 markdown 真源。

## 裁决结果

2026-11-19 负责人接受本 ADR：

1. 接受本 ADR，并同意把 `rawstore.py` 抽为 `memhub.queue` 的独立分层变更
   （已随 `464c604` 落地）。
2. 本次不新增 `source_type=upload`，MVP 复用 `docs`，节点溯源仍记 `wiki`；
   该枚举变更单独立项。
3. 接受「上传后长时间停留在 queued 属正常排队」作为对外语义
   （worker 只在窗口期搬运 raw 文件）。

## 后果

- 新增依赖：无。`python-multipart` 已在 `engine` extra（semantica explorer 使用）。
- 上传内容只进入 raw_store 与 LLM 抽取路径，不直接写 `knowledge/`；提示词沿用
  `prompts/wiki.md` 的「只抽取文档明确写出的内容」约束，上传文档视为不可信数据。
- 运维新增约束：kb-api / ingest-api / worker 必须共享同一 `MEMHUB_DATA_DIR`。
- kb-admin 错误码区间由 1010–1012 扩展到 1013，需同步契约文档与前端映射。
- worker、prompts、node schema、ingest 采集契约均不改动。

## 备选与否决理由

- **浏览器直接调 `POST /api/v1/ingest/raw`**：需要 device token、batch 幂等与游标推进，浏览器既无令牌也不应拥有采集端游标；否决。
- **kb-api 解析文档后直接写 `knowledge/`**：绕过 LLM 抽取与 `tier=candidate` 治理，把「上传」变成「直写真源」，与 ADR-0002 的入库边界冲突；否决。
- **新增独立上传/抽取服务**：与 worker 重复 LLM 成本与提示词治理，部署面扩大；否决。
- **只提供 CLI 导入**：无法满足管理台的可视化上传与状态反馈；作为降级备选保留。
