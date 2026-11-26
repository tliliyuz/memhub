# 长期记忆子系统实施规格

| 属性 | 值 |
|:---|:---|
| 文档状态 | specified |
| 最后更新 | 2026-11-26 |
| 适用范围 | 长期记忆的表结构、聚合任务、快照发布、会话抽取注入、审计、管理 API 与管理台 |
| 不负责 | 方向与边界（见 [ADR-0016](../decisions/ADR-0016-long-term-memory.md)）、通用开发流程（见 [DEVELOPMENT](../guides/DEVELOPMENT.md)） |

本规格承接 [ADR-0016](../decisions/ADR-0016-long-term-memory.md)，只覆盖第一期：把
「从跨项目会话中提炼的准则」做成独立记忆域，并注入**会话抽取**提示词。MCP 只读工具、
影子抽取对照、向量检索与以原始会话为主证据的聚合均不在本期。

## 1. 目标与范围

第一期必须做到：

1. 记忆条目不挂在 `kb_projects` 下，不使用 `<project>/<kind>/<slug>` id，不新增 `Kind`，
   不进入 `kb_nodes` 检索，不能作为采集目标。
2. 只有周期聚合任务（系统 actor）与管理台负责人能写记忆；采集端、MCP 写工具、会话抽取
   worker 都不能写条目。
3. 聚合以跨项目 canonical 节点为证据；默认门槛为「≥3 个独立会话且 ≥2 个项目」，
   未达门槛只保留候选，不成条。
4. 记忆以版本化快照发布；会话抽取在一个进程生命周期内固定使用启动时读到的那一版，
   每次抽取在 `kb_write_audit` 记录所用版本。
5. 注入只取 `active` 条目，按 BM25 相关性取 top-k 并受字符预算约束；可按项目关闭。
6. 管理台有独立的「长期记忆」入口，能看条目、候选与快照，并执行发布、回滚、停用、废弃。

本期不实现：MCP 记忆工具、记忆写入采集/MCP 路径、记忆之间的自动合并、聚合任务读取记忆、
记忆进入项目库检索、按记忆版本重放历史抽取结果。

## 2. 术语与边界

- **条目（entry）**：一条有版本、有证据、可废弃的准则，主键是全局唯一的 kebab-case `slug`。
- **候选（candidate）**：聚合产出但未达门槛、或与现有条目冲突的结果。候选只读暂存，
  不能直接转正；后续聚合达到门槛时自动转正，冲突由负责人编辑或废弃条目裁决。
- **快照（snapshot）**：某一时刻全部 `active` 条目的不可变副本，可整体发布、回滚、停用。
- **独立会话**：证据节点的 `source` 中 `type=session` 的来源引用，按 `(project, ref)` 去重。
  一个节点可在多次会话中被再次写入；只按来源引用计数，不按节点数计数。
- **记忆全局共享**：一条记忆跨所有项目生效，注入时不做库范围授权过滤。

## 3. 数据模型

迁移为 `alembic/versions/0005_long_term_memory.py`（合入 dev 后接在 `0004_mcp_trace_funnel` 之后），与 `memhub.kb.models.Base` 零差异。
四张表都与其他 `kb_*` 表同 schema，不使用外键指向 `kb_projects`。

### 3.1 `kb_memory_entries`

| 列 | 类型 | 约束 |
|:---|:---|:---|
| `slug` | text | 主键；`^[a-z0-9][a-z0-9-]{0,99}$` |
| `title` | text | 非空，1–200 字符 |
| `conclusion` | text | 非空，一句话结论 |
| `boundary` | text | 非空，可空串；适用边界 |
| `invalidation` | text | 非空，可空串；失效条件或反例 |
| `evidence` | jsonb | 非空，默认 `[]`；元素见 §3.1.1 |
| `confidence` | double precision | 非空，默认 `0.5`；`0 ≤ x ≤ 1` |
| `status` | text | 非空，默认 `active`；`active` / `deprecated` |
| `deprecated_reason` | text | 可空 |
| `superseded_by` | text | 可空；指向另一条目的 `slug`，仅作引用，不加外键 |
| `contradicts` | text[] | 非空，默认 `{}`；冲突条目 slug |
| `revision` | text | 非空；16 位小写 hex，每次写入重算 |
| `created_at` / `updated_at` | timestamptz | 非空 |

索引：`ix_kb_memory_entries_status`（`status`, `updated_at`）、
`ix_kb_memory_entries_updated`（`updated_at`）。

#### 3.1.1 证据元素

```json
{
  "node_id": "proj/fact/retry-backoff",
  "project": "proj",
  "session": "proj:2026-11-20.jsonl",
  "session_ref": "2026-11-20.jsonl",
  "observed_at": "2026-11-20T10:00:00+00:00"
}
```

`node_id` 与 `project` 必填；`session` 是 `project + ":" + session_ref` 的去重键，
节点没有任何 session 来源时为 `null`。证据只允许来自本次聚合输入中的 canonical 活动节点，
不接受模型自造 id。`observed_at` 取节点的 `updated_at`。

### 3.2 `kb_memory_revisions`

| 列 | 类型 | 约束 |
|:---|:---|:---|
| `id` | bigint | 主键，自增 |
| `slug` | text | 非空 |
| `revision` | text | 非空；写入后的条目 revision |
| `actor` | text | 可空；`memory-aggregate` / `ui` |
| `reason` | text | 可空 |
| `before` | jsonb | 非空；新建时 `{}` |
| `after` | jsonb | 非空；完整条目快照 |
| `created_at` | timestamptz | 非空 |

索引：`ix_kb_memory_revisions_slug`（`slug`, `created_at`）。修订不删除、不改写。

### 3.3 `kb_memory_snapshots`

| 列 | 类型 | 约束 |
|:---|:---|:---|
| `version` | bigint | 主键，自增 |
| `status` | text | 非空；`published` / `superseded` / `disabled` |
| `entries` | jsonb | 非空；发布时的 active 条目数组 |
| `item_count` | integer | 非空；`entries` 长度 |
| `note` | text | 非空，默认 `""` |
| `actor` | text | 可空；发布者 |
| `created_at` | timestamptz | 非空 |
| `published_at` | timestamptz | 可空 |

部分唯一索引 `uq_kb_memory_snapshots_published`（`status`，`WHERE status = 'published'`）
保证至多一个已发布快照。`entries` 每项含 `slug`、`title`、`conclusion`、`boundary`、
`invalidation`、`confidence`、`evidence`；不冻结 `updated_at` 之外的条目元数据。

### 3.4 `kb_memory_candidates`

| 列 | 类型 | 约束 |
|:---|:---|:---|
| `id` | bigint | 主键，自增 |
| `slug` | text | 非空，唯一 |
| `title` / `conclusion` / `boundary` / `invalidation` | text | 同条目 |
| `evidence` | jsonb | 非空 |
| `confidence` | double precision | 非空 |
| `session_count` / `project_count` | integer | 非空 |
| `status` | text | 非空；`pending` / `conflict` / `promoted` |
| `reason` | text | 非空；`below_threshold` / `conclusion_differs` / `deprecated` |
| `contradicts` | text[] | 非空，默认 `{}` |
| `first_seen_at` / `last_seen_at` | timestamptz | 非空 |
| `created_at` / `updated_at` | timestamptz | 非空 |

每个 slug 只保留一行最新候选；`promoted` 只表示最近一次聚合已把它写成条目，仍保留供审计。

### 3.5 审计列

`kb_write_audit` 增加 `memory_snapshot bigint NULL`。会话抽取审计与快照生命周期审计都写这一列，
不写记忆正文。

## 4. 条目写入

写入者只有两个：

- 周期聚合命令 `memhub memory-aggregate`，actor 固定 `memory-aggregate`；
- 管理台 API，actor 默认 `ui`。

条目写入一律在 `write_scope` 事务内完成，同时追加一条 `kb_memory_revisions`。更新与废弃带
`expected_revision` 时做乐观锁：不一致抛 `RevisionConflict`（HTTP 409）。新建条目时
`expected_revision` 必须为空；同一 slug 已存在则抛冲突，聚合任务按 §5.4 处理。

内容校验（存储层与 API 共用）：

- `slug` 必须匹配 `^[a-z0-9][a-z0-9-]{0,99}$`；
- `title` 去空白后 1–200 字符；`conclusion` 去空白后非空；
- `boundary`、`invalidation` 允许空串，但不接受 `null`；
- `confidence` 在 `[0, 1]`；
- `evidence` 每个元素必须有 `node_id` 与 `project`；`contradicts` 只接受合法 slug 且不含自身；
- `superseded_by` 只能指向已存在的条目；废弃时若给 `superseded_by`，目标必须是 `active`。

废弃语义：`status='deprecated'`、写 `deprecated_reason`、可选 `superseded_by`，不物理删除。
已废弃条目不能被聚合任务改写或复活。

## 5. 周期聚合

### 5.1 输入选择

`memory-aggregate` 读取最近 `--since-days`（默认 7）天内更新过的 canonical、未软删节点，
`kind` 限于 `fact`、`decision`、`procedure`、`pitfall`，按 `updated_at` 倒序，最多
`--max-nodes`（默认 100）条。正文单条截断到 600 字符；总输入超过 60000 字符时从最旧开始丢弃。
聚合任务**不读取任何记忆条目或快照**。

### 5.2 提示词与响应契约

提示词为 `prompts/memory.md`。输入是逐行 JSON 的节点清单；模型只返回一个 JSON 对象：

```json
{
  "memories": [
    {
      "slug": "verify-before-refactor",
      "title": "改结构前先补验证",
      "conclusion": "在重构前先补能复现行为的测试或对照输出。",
      "boundary": "适用于已有可执行入口的代码库。",
      "invalidation": "没有可运行入口且无法构造对照时不适用。",
      "confidence": 0.8,
      "evidence": ["proj-a/fact/verify-first", "proj-b/decision/test-before-refactor"],
      "contradicts": []
    }
  ]
}
```

响应逐项校验：`slug` 归一化后必须合法；`title`、`conclusion` 非空；`confidence` 缺失按 0.5、
越界截到 `[0, 1]`；`evidence` 必须是非空字符串数组，且每项都在本次输入 id 集合内，否则丢弃该项
而不是整批失败。结构坏（不是 JSON、`memories` 不是数组）整次失败，退出码 1。

### 5.3 门槛

`session_count` 与 `project_count` 由输入节点**实际来源**计算，不信任模型：

- 项目数 = 证据节点 `project` 去重数；
- 会话数 = 证据节点 `source` 中 `type=session` 的 `(project, ref)` 去重数；
- 门槛默认 `--min-sessions 3`、`--min-projects 2`，参数可覆盖但不允许小于 1。

同时满足才写成 `active` 条目；否则写 `kb_memory_candidates`，`status='pending'`、
`reason='below_threshold'`，保留证据关联。候选不计入快照、不注入。

### 5.4 与现有条目的关系

按 slug 查现有条目：

| 现状 | 动作 |
|:---|:---|
| 不存在，达门槛 | 新建 active 条目；写修订；候选置 `promoted` |
| 不存在，未达门槛 | 新建/更新候选 `pending` / `below_threshold` |
| 存在 active，结论规范化后相同 | 证据取并集合并、重算计数；用新的 `boundary`/`invalidation`/`confidence` 更新；`revision` 重算并写修订 |
| 存在 active，结论不同 | 不改条目；候选置 `conflict` / `conclusion_differs`，`contradicts=[现有 slug]` |
| 存在 deprecated | 不改条目；候选置 `conflict` / `deprecated` |
| 存在候选且 slug 相同 | 覆盖候选内容与计数，状态按本次结果重算 |

「结论相同」指 Unicode NFC、大小写折叠、空白折叠后完全一致；不做语义相似判断。
聚合任务不自动合并冲突、不改 `status`、不删除证据。

### 5.5 CLI

```text
memhub memory-aggregate [--since-days N] [--min-sessions N] [--min-projects N]
                         [--max-nodes N] [--dry-run] [--publish]
```

- 需要 `MEMHUB_KB_DB_URL` 与 LLM 配置，缺任一退出 2；
- 模型取 `MEMHUB_LLM_MODEL_MEMORY`，未设置时回退 `MEMHUB_LLM_MODEL_EXTRACT`；
- `--dry-run` 仍然调用模型，但只打印每条记忆的 slug、计数与将执行的动作，不写库；
- `--publish` 在写入成功后发布新快照，`note` 为 `aggregate since=<days>d`；
- 无候选节点时打印「没有可聚合节点」并退出 0；
- 输出只含 slug、计数、动作，不打印记忆正文与提示词。

### 5.6 周期调度

部署侧新增 `memhub-memory-aggregate.timer`（每周，默认周一 03:00 本地时区），执行
`memhub memory-aggregate --publish`。调度不在应用进程内；系统 clock 与 worker 窗口时区
无关。定时器安装属部署变更，本轮只提交 unit 文件与文档，不安装到生产。

## 6. 快照发布、回滚、停用

- **发布**：读全部 `active` 条目生成新快照；同一事务内先把现有 `published` 改为 `superseded`，
  再插入新行 `status='published'`、`published_at=now`。允许发布空快照（`item_count=0`）。
- **回滚**：`activate(version)` 把目标快照改回 `published`，把当前 `published` 改为 `superseded`。
  只能回滚到 `superseded` 的快照；已是 `published` 时幂等返回；`disabled` 不能重新激活。
- **停用**：`disable(version)` 只接受当前的 `published`，置 `disabled`。停用后没有已发布快照，
  抽取不再注入记忆；恢复靠发布新快照或回滚到旧快照。
- 发布、回滚、停用都写 `kb_write_audit`：`action` 分别为 `memory_snapshot_publish`、
  `memory_snapshot_activate`、`memory_snapshot_disable`，`memory_snapshot=version`，
  `result` 为 `ok`，`actor` 取操作者。
- worker 启动时读一次 `published` 快照，把 `version` 与条目固定在进程内；快照变更要重启
  worker 才生效，这是 ADR 要求的冻结语义，不是缓存缺陷。

## 7. 注入与审计

### 7.1 选择

每次会话窗口抽取前，用窗口文本按 BM25 对快照条目打分，候选文档为
`title + "\n" + conclusion + "\n" + boundary`。只取分数大于 0 的条目，按分数降序取
`MEMHUB_MEMORY_TOP_K`（默认 8，允许 1–10）条；按顺序累加，超过
`MEMHUB_MEMORY_INJECT_CHARS`（默认 4000）字符时停止。没有任何分数大于 0 的条目时不注入。

注入块格式：

```text
长期记忆（判断与归一化准则；不是事实来源，不得写入 evidence）：
- [slug] 结论
  边界：...
  失效条件：...
```

没有注入时渲染为 `（本次未注入长期记忆）`。提示词 `prompts/sessions.md` 增加该段，
并明确：记忆只用于判断、归一化与去重，不能作为证据引用，不能覆盖本窗原文。

### 7.2 按项目关闭

`MEMHUB_MEMORY_INJECT_DISABLED_PROJECTS` 是逗号分隔的库 id 列表；命中时该项目不注入，
审计仍记录 `memory_snapshot=null` 与 `result`。

### 7.3 证据边界

`extract_session` 只接受本窗 `new` 块中的逐字引用，记忆文本不进入块集合，因此模型即使
把记忆内容抄进 `quote` 也无法通过校验。本期依赖这一既有门禁，不为记忆另加证据通道。

### 7.4 审计

worker 每完成一次会话文件抽取（包括抽取结果为空）写一行：

| 列 | 值 |
|:---|:---|
| `actor` | `worker` |
| `project` | 目标库 |
| `node_id` | `null` |
| `action` | `extract_session` |
| `result` | `ok`（有节点）/ `empty`（无节点） |
| `memory_snapshot` | 进程固定的快照版本；未发布或项目关闭时为 `null` |

审计写入失败按现有约定上抛，不静默丢弃。`memhub ingest --profile sessions` 的手工路径
同样注入并审计，保证两条会话抽取路径口径一致。

## 8. 管理 API

新增路由，沿用 `kb-admin-api.md` 的错误包络与 503 约定：

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/memories` | `status=active/deprecated/all`、`q`、`limit`、`offset`；返回 `{items,total,offset,limit}` |
| GET | `/api/v1/kb/memories/{slug}` | 单条 + 最近 20 条修订 |
| PATCH | `/api/v1/kb/memories/{slug}` | `expected_revision` 必填；可改 `title`/`conclusion`/`boundary`/`invalidation`/`confidence`/`contradicts` |
| POST | `/api/v1/kb/memories/{slug}/deprecate` | `expected_revision`、`reason` 必填，`superseded_by` 可选 |
| GET | `/api/v1/kb/memories/candidates` | `status=pending/conflict/promoted/all`；`{items,total}` |
| GET | `/api/v1/kb/memories/snapshots` | 倒序；含 `entries` 与计数 |
| POST | `/api/v1/kb/memories/snapshots` | 发布；body `{note?, actor?}` |
| POST | `/api/v1/kb/memories/snapshots/{version}/activate` | 回滚 |
| POST | `/api/v1/kb/memories/snapshots/{version}/disable` | 停用；body `{reason?}` |

路由顺序：`/memories/candidates` 与 `/memories/snapshots` 必须先于 `/memories/{slug}` 注册，
避免被当成分 slug。非 PG 存储统一返回 503 / `2001`（与 `/mcp-traces` 一致）。
错误映射：不存在 404 / `1011`；乐观锁与状态冲突 409 / `1010`；参数非法 422 / `1012`。

## 9. 管理台

侧栏「治理」组新增「长期记忆」，路由 `/_app/memories`。页面包含：

- 顶部摘要：active / deprecated 条目数、待处理候选数、当前快照版本；
- 条目表：slug、标题、结论、置信度、状态、更新时间和「废弃」操作（要求填写原因）；
- 候选表：slug、结论、会话数/项目数、状态与原因，冲突候选用醒目徽标；
- 快照表：版本、状态、条目数、发布时间，提供「发布新快照」「回滚」「停用」按钮；
  操作前用 `window.confirm` 二次确认，失败时展示 `ApiError.message`。

页面只展示记忆元数据与结论，不展示证据正文。发布/回滚/停用后刷新列表。

## 10. 配置键

| 键 | 默认 | 读取方 | 非法时 |
|:---|:---|:---|:---|
| `MEMHUB_MEMORY_TOP_K` | `8` | worker / ingest | 非 1–10 整数退出 2 |
| `MEMHUB_MEMORY_INJECT_CHARS` | `4000` | worker / ingest | 非正整数退出 2 |
| `MEMHUB_MEMORY_INJECT_DISABLED_PROJECTS` | 空 | worker / ingest | 忽略空白项；不校验库是否存在 |
| `MEMHUB_LLM_MODEL_MEMORY` | 空（回退 `MEMHUB_LLM_MODEL_EXTRACT`） | `memory-aggregate` | 两者都缺时退出 2 |

键集同步写入 `docs/tech/ENVIRONMENT.md`、`.env.example` 与本机 `.env`（未知值留空）。

## 11. 验收条件

| 编号 | 条件 |
|:---|:---|
| AC-1 | Alembic `upgrade head` 建出四张记忆表与 `kb_write_audit.memory_snapshot`；`compare_metadata` 零差异；`downgrade base` 干净 |
| AC-2 | 条目新建/更新/废弃都追加一条修订，`revision` 每次重算；带过期 `expected_revision` 的更新返回冲突且不覆盖 |
| AC-3 | 同一时刻至多一个 `published` 快照；发布新版本会把旧版本置 `superseded`；回滚把目标置 `published`；停用当前版本后没有 published |
| AC-4 | 发布、回滚、停用各写一条 `kb_write_audit`，`memory_snapshot` 与版本一致 |
| AC-5 | 聚合响应中的证据 id 不在输入集合时丢弃该条；整批结构坏时命令失败 |
| AC-6 | 证据覆盖 ≥3 会话且 ≥2 项目时写 active 条目；少一个条件只写 `pending` 候选，不产生条目、不进快照 |
| AC-7 | 同 slug 结论相同合并证据并重算计数；结论不同只写 `conflict` 候选，不改现有条目；已废弃条目不复活 |
| AC-8 | 聚合任务不读取记忆表（以测试替身断言无 `current_snapshot`/条目读取调用） |
| AC-9 | 注入只选分数 > 0 的 `active` 条目，遵守 top-k 与字符预算；项目命中禁用列表时不注入 |
| AC-10 | `extract_session` 渲染出的提示词包含记忆块；记忆文本不能充当逐字证据 |
| AC-11 | worker 抽取后写 `extract_session` 审计，`memory_snapshot` 等于进程固定版本；空结果也记录 |
| AC-12 | 管理 API 的列表过滤、分页、PATCH 乐观锁、废弃、发布/回滚/停用与错误码符合 §8 |
| AC-13 | 管理台「长期记忆」入口可见，页面能展示三类数据并完成发布、回滚、停用；前端单测覆盖查询串与错误映射 |
| AC-14 | 全量 `pytest`（含 PG 用例）与 `ruff check`、`ruff format --check`、`mypy src`、前端构建通过 |

## 12. 裁决记录与待评审事项

- 2026-11-26：负责人指令「继续 ADR-0016」，ADR-0016 转 `accepted`，按 ADR 默认值落本规格并进入实施。
  表名、字段、门槛与入口以本文件为准；未另行逐条评审。
- 2026-11-26：§8 原写「冲突 409 / `1012`、参数非法 422 / `1011`」，与权威契约
  `docs/contracts/kb-admin-api.md` 的 `1010` 冲突、`1011` 不存在、`1012` 非法不一致。
  按文档矩阵以契约为准修正为 409 / `1010`、422 / `1012`；实现与验收测试按契约断言。
- 2026-11-26：负责人接受 ADR-0019（MCP 只读长期记忆工具），原「记忆是否需要只读 MCP 工具」待评审项结案：新增 `kb_memory_search` / `kb_memory_read`，数据面只读当前 `published` 快照中的 `active` 条目，由 `Grant.memory` 显式开启；契约见 `docs/contracts/mcp-tools.md` 0.9。该能力属于后续里程碑，不改变本规格 §3 的写入边界。
- 待评审：候选是否增加「人工拒绝」动作（本期候选只读，冲突靠编辑/废弃条目裁决）。
- 待评审：聚合输入是否回读原始会话抽样核对（本期只用 canonical 节点）。
