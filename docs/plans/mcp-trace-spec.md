# MCP 调用轨迹：实施规格

| 属性 | 值 |
|:---|:---|
| 文档状态 | draft（待负责人评审） |
| 最后更新 | 2026-11-26 |
| 适用范围 | `kb_mcp_trace` 数据模型、记录语义（含发现层事件）、可靠落库、保留期、管理台 API 与页面、验收条件 |
| 不负责 | 架构裁决（见 [ADR-0015](../decisions/ADR-0015-mcp-call-trace.md)、[ADR-0017](../decisions/ADR-0017-mcp-discovery-trace.md)）、MCP 工具契约（见 [mcp-tools.md](../contracts/mcp-tools.md)）、管理台接口总表（见 [kb-admin-api.md](../contracts/kb-admin-api.md)） |

## 1. 目标与范围

承接 [ADR-0015](../decisions/ADR-0015-mcp-call-trace.md)：让「MCP 到底被调用了多少次、被谁调用、成没成功、慢不慢」在服务端有唯一可查的真源，并在管理台「治理」菜单下可见。

### 1.1 本轮范围

- `kb_mcp_trace` 表与 Alembic `0002` / `0004` 迁移。
- HTTP MCP 入口的记录：`tools/call`、鉴权/路由拒绝，以及发现层的 `initialize` 与 `tools/list`（ADR-0017）。
- 可靠的写入路径（独立事务 + 重试 + 本地 spool 补投）。
- 凭据可选 `name` 与降级显示。
- 30 天保留的节流清理。
- 管理台列表接口、汇总漏斗口径与「调用轨迹」页面。

### 1.2 不在本轮

- 客户端侧统计（transcript / hook）与「主动 vs 被动调用」的区分。
- MCP 工具描述、`instructions` 与渐进式披露策略的调整（P1，另开分支）。
- 调用参数原文、正文或任何会话内容的记录。
- 多副本部署下的分布式聚合。
- 日聚合表与超过 30 天的趋势。

## 2. 数据模型

### 2.1 `kb_mcp_trace`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `id` | bigserial PK | |
| `trace_id` | text not null unique | 每次记录一个 UUID4 hex；重试复用同一值，保证幂等 |
| `request_id` | text not null | HTTP 请求 id，入口生成；批量请求下可重复 |
| `rpc_id` | text null | JSON-RPC `id` 的字符串形式；通知与拒绝为空 |
| `called_at` | timestamptz not null | 请求进入入口的时间，UTC |
| `event` | text not null | `call`（`tools/call` 与拒绝）/ `list_tools` / `initialize`；历史行迁移后为 `call` |
| `credential_id` | text null | 凭据摘要前 12 位（`grant_id`）；无效 token 为空 |
| `credential_name` | text null | 写入时的凭据名快照；未配置则为空 |
| `tool` | text null | `tools/call` 的工具名；发现层事件与拒绝记录为空 |
| `status` | text not null | `ok` / `error` / `rejected` |
| `http_status` | integer not null | 该 HTTP 请求的响应码（成功调用与发现层事件为 200） |
| `error_code` | integer null | JSON-RPC 错误码（`isError` 时取 `data.code`） |
| `error_kind` | text null | 稳定分类：`invalid_params` / `unauthorized` / `forbidden` / `method_not_allowed` / `rate_limited` / `not_found` / `internal` |
| `duration_ms` | integer not null | 见 §3.2 |
| `result_bytes` | integer null | 返回内容序列化后的 UTF-8 字节数；拒绝与发现层事件为空 |
| `args_digest` | text null | 参数规范化 JSON 的 sha256 hex；不存原文 |
| `projects` | text[] null | 凭据授权项目范围的快照 |
| `client` | text null | `User-Agent`，截断至 256 字符 |
| `tool_count` | integer null | `tools/list` 成功返回的工具数；其余事件为空 |

索引：`ix_kb_mcp_trace_called_at (called_at)`；`ix_kb_mcp_trace_tool (tool, called_at)`；`ix_kb_mcp_trace_credential (credential_id, called_at)`；`ix_kb_mcp_trace_status (status, called_at)`；`ix_kb_mcp_trace_event (event, called_at)`。实现上均为升序 B-tree；列表的 `ORDER BY called_at DESC` 由 Postgres 反向扫描满足，无需显式 `DESC` 索引。

约束：不设外键；`status` 用应用层枚举，库内不建 CHECK（与既有表的取值约束口径一致）。

### 2.2 凭据名

`Grant` 增加可选字段 `name`：

- 类型：字符串，`strip()` 后 1–64 字符，不允许控制字符；未提供时为 `None`。
- `authorize()` 把它放进 `Credential.name`。
- 记录时写快照；展示时 `credential_name or credential_id or "unknown"`。
- 旧配置（无 `name`）照常启动，不报错。

## 3. 记录语义

### 3.1 记录的触发点

| 场景 | `event` | 记录时机 | 关键字段 |
|---|---|---|---|
| `tools/call` 成功 | `call` | `call_tool` 返回且 `isError=false` | `status=ok`，`http_status=200` |
| `tools/call` 业务错误 | `call` | `call_tool` 返回 `isError=true` | `status=error`，`error_code` 取 `data.code` |
| `tools/call` 未预期异常 | `call` | 异常上抛前 | `status=error`，`error_kind=internal`，异常继续上抛 |
| 无效/缺失 token | `call` | 入口返回 401 前 | `status=rejected`，`error_kind=unauthorized`，凭据为空 |
| 带 `Origin` | `call` | 入口返回 403 前 | `error_kind=forbidden` |
| 非 POST | `call` | 入口返回 405 前 | `error_kind=method_not_allowed` |
| 入口限流 | `call` | 入口返回 429 前 | `error_kind=rate_limited` |
| `initialize` 成功/失败 | `initialize` | SDK 中间件在握手返回/异常前 | `status=ok/error`，`tool` 为空 |
| `tools/list` 成功/失败 | `list_tools` | SDK 中间件在列表返回/异常前 | 成功时 `tool_count` 为返回工具数 |
| 非 `/mcp` 路径 | — | **不记录** | — |

`notifications/*`、`ping` 不记录：它们不构成「连接 → 列工具 → 调用」漏斗中的任何一步。`initialize` 每发生一次算一次连接尝试；`tools/list` 每成功返回一次算一次「看到工具」。发现层事件会随凭据作用域变化（`mcp:read` 4 个工具、`mcp:write` 7 个），因此 `tool_count` 只描述该次返回，不做跨凭据合并。

### 3.2 耗时定义

- `tools/call`：从进入 `invoke` 回调到结果准备好上抛，单调时钟差值，向上取整毫秒。
- 拒绝：从入口匹配到 `/mcp` 到响应对象构造完成。
- `initialize` / `tools/list`：从 SDK 中间件进入处理器到结果准备好（或异常抛出），单调时钟差值，向上取整毫秒。
- `called_at` 用请求进入入口的时间，不是写入时间。

### 3.3 参数摘要

`args_digest = sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":")))`。
参数无法规范化（非 JSON 兼容）时为空，不阻断调用。

## 4. 可靠落库

### 4.1 写入语义

1. 每次记录先生成 `trace_id` 并构造完整行。
2. 用独立 session 写入并提交；失败按 100ms / 300ms 退避重试，最多 3 次。
3. 重试仍失败 → 追加一行 JSON 到 spool 文件并 `flush` + `os.fsync`，同时记 WARNING。
4. 下一次成功写入前，先尝试把 spool 中的行补投到 PG（`ON CONFLICT (trace_id) DO NOTHING`），成功后截断 spool。
5. spool 也不可用（无路径、无权限、盘满）→ 记 ERROR，调用本身照常返回；这是唯一会丢记录的路径，必须告警。

### 4.2 spool 位置与格式

- 路径优先级：`MEMHUB_KB_TRACE_SPOOL` → `$MEMHUB_DATA_DIR/mcp_trace_spool.jsonl` → 未配置则 spool 关闭。
- 每行一个 JSON 对象，键与表列一致；`called_at` 用 ISO-8601 UTC 字符串。
- 单文件；补投成功或文件超过 8 MiB 时重写为剩余部分（原子替换）。

### 4.3 与调用的关系

- 记录写入失败**不得**改变 `tools/call` 的返回内容或状态码。
- 但必须留日志与 spool，不允许静默吞掉。

## 5. 保留期

- 明细保留 30 天。
- 清理在写入路径上按小时节流：距上次清理超过 3600 秒时，执行 `DELETE FROM kb_mcp_trace WHERE called_at < now() - interval '30 days'`。
- 清理失败只记 WARNING，不影响记录写入。
- 无调用时可能长期不清理，属可接受行为。

## 6. 管理台 API

### 6.1 列表

`GET /api/v1/kb/mcp-traces`

| 参数 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `limit` | int | 50 | 1–500 |
| `offset` | int | 0 | ≥ 0 |
| `event` | str | `call` | `call` / `list_tools` / `initialize`；默认只看调用与拒绝，保持既有语义 |
| `tool` | str | — | 精确匹配 |
| `status` | str | — | `ok` / `error` / `rejected` |
| `credential` | str | — | 匹配 `credential_id` 或 `credential_name` |
| `since` | datetime | — | ISO-8601，闭区间 |
| `until` | datetime | — | ISO-8601，闭区间 |

返回：

```json
{
  "items": [
    {
      "trace_id": "…", "request_id": "…", "rpc_id": "2",
      "called_at": "2026-11-25T06:11:49.123456+00:00",
      "credential": {"id": "a1b2c3d4e5f6", "name": "claude-code-laptop"},
      "event": "call", "tool": "kb_search", "status": "ok", "http_status": 200,
      "error_code": null, "error_kind": null,
      "duration_ms": 18, "result_bytes": 1024, "tool_count": null,
      "projects": ["memhub"], "client": "claude-code/2.x"
    }
  ],
  "total": 1, "offset": 0, "limit": 50
}
```

`credential.display` 不出现在接口里，由前端按 `name || id || "unknown"` 渲染，避免把展示规则固化进契约。

排序：`called_at` 倒序，同刻按 `id` 倒序。

### 6.2 汇总

`GET /api/v1/kb/mcp-traces/summary?days=7`

- `days`：1–30，默认 7。
- `avg_ms`：该工具 `ok` 与 `error` 调用的 `duration_ms` 平均值（四舍五入取整）；`rejected` 不参与，无可算调用时为 0。
- 漏斗口径（同一时间窗，按 `event` 分组）：
  - `connections`：`initialize` 且 `status=ok` 的行数（连接次数）。
  - `listings`：`list_tools` 且 `status=ok` 的行数（看到工具的次数）。
  - `calls`：`call` 且 `status in (ok, error)` 的行数（实际调用；`rejected` 不算调用，仍单独统计）。
  - 转化率 `listings_per_connection = listings / connections`、`calls_per_listing = calls / listings`，分母为 0 时记 `0.0`；`avg_tools` 为该窗口内 `list_tools` 成功行 `tool_count` 的平均值（无行时 0）。
- 返回：

```json
{
  "since": "2026-11-18T…", "days": 7,
  "total": 120, "ok": 96, "error": 18, "rejected": 6,
  "tools": [{"tool": "kb_search", "count": 80, "ok": 70, "error": 10, "rejected": 0, "avg_ms": 21}],
  "credentials": [{"id": "a1b2c3d4e5f6", "name": "claude-code-laptop", "count": 120}],
  "funnel": {"connections": 9, "listings": 12, "calls": 114,
             "listings_per_connection": 1.33, "calls_per_listing": 9.5, "avg_tools": 7.0}
}
```

`total / ok / error / rejected / tools / credentials` 只统计 `event=call` 的行，口径与漏斗上线前一致。

### 6.3 错误

- 参数非法：沿用 FastAPI 校验的 422。
- 存储不可用（非 PG store）：`503` + `code=2001`。

## 7. 管理台页面

- 侧栏「治理」下新增 `调用轨迹`，路径 `/traces`，图标用 `Activity`（lucide）。
- 页面结构：
  - 顶部汇总：总数、成功、失败、拒绝、按工具分布；
  - 漏斗区块：连接数（`initialize`）、列工具数（`tools/list`）、实际调用数（`call` 的成功 + 失败），以及两段转化率与平均每次列出的工具数；分母为 0 时显示 `—`；
  - 筛选：工具、状态、凭据、时间范围（近 1/7/30 天）；
  - 表格：时间、请求 ID（截前 8 位，悬停见完整值）、工具、凭据（降级显示）、状态、HTTP、错误码、耗时、结果大小、客户端；
  - 分页与「共 N 条」。
- 空态文案明确说明「30 天明细，更早数据已清理」。

## 8. 契约与文档同步

- `docs/contracts/kb-admin-api.md` §4.9「MCP 调用轨迹」同步发现层字段与漏斗。
- `docs/contracts/mcp-tools.md` §5「可观测性」同步发现层记录范围。
- `docs/tech/ENVIRONMENT.md` 新增 `MEMHUB_KB_TRACE_SPOOL`（可选）并说明失败语义。
- `docs/decisions/README.md` 登记 ADR-0015 与 ADR-0017。
- `docs/plans/README.md` 登记本规格。
- `docs/CHANGELOG.md` 行为变更记录。

## 9. 验收条件

以下每条都对应可执行测试，先制造 RED 再实现。

### 9.1 记录

1. 成功的 `tools/call` 产生一行：`status=ok`、`tool` 正确、`duration_ms>=0`、`result_bytes>0`、`credential_id` 非空、`projects` 与凭据一致。
2. `isError` 的调用产生 `status=error`，`error_code` 与返回 `data.code` 一致。
3. 凭据配置了 `name` 时 `credential_name` 等于该值；未配置时为 `null`（展示层降级到 `credential_id`）。
4. 无效 token 的请求产生 `status=rejected`、`error_kind=unauthorized`、`credential_id=null`。
5. 带 `Origin` 的请求产生 `error_kind=forbidden`；非 POST 产生 `method_not_allowed`。
6. 参数原文不出现在表内任何列：用含唯一标记的查询做反证。
7. 一次连接 + 列表 + 调用产生三条记录：`initialize`（`tool_count=null`）、`list_tools`（`tool_count=4` 或 `7`，与凭据作用域一致）、`call`（`tool` 为被调工具）；三者的 `request_id`、`credential_id/name`、`client` 都非空。
8. `notifications/*` 与 `ping` 不产生记录。

### 9.2 可靠落库

9. 注入一次写入失败（session 抛错）后，行出现在 spool 文件；下一次成功记录时补投到表，spool 被清空。
10. 重试成功后不产生重复行（同一 `trace_id` 只一行）。
11. 写入彻底失败时调用返回内容不变、状态码不变。

### 9.3 保留期

12. `called_at` 早于 30 天的行在触发清理后消失；新行保留。
13. 清理节流：两次写入不重复执行清理（以注入的时钟或计数断言）。

### 9.4 API 与页面

14. 列表接口返回 `{items,total,offset,limit}`，按时间倒序，过滤条件生效；默认 `event=call`，显式 `event=list_tools` 能取到发现层行。
15. 汇总接口按 `days` 聚合，`total = ok + error + rejected`；`funnel.connections/listings/calls` 与插入行一致，转化率按 §6.2 计算，分母为 0 时为 `0.0`。
16. 非 PG 存储时返回 503/`2001`。
17. 前端 `pnpm build` 通过；页面能展示空态、有数据与漏斗区块。

### 9.5 迁移

18. Alembic `upgrade head` 后 `compare_metadata` 与 `Base.metadata` 零差异，`kb_mcp_trace` 含 `event`、`tool_count` 与事件索引；历史行 `event=call`。
19. `downgrade base` 干净移除。

## 10. 裁决记录

| 事项 | 裁决 | 日期 |
|---|---|---|
| 凭据名缺失时的显示 | 降级显示 `credential_id` | 2026-11-25 |
| 明细保留期 | 30 天 | 2026-11-25 |
| 写入语义 | 可靠落库（重试 + 本地 spool），不接受 best-effort | 2026-11-25 |
| 发现层事件是否落库 | 并入 `kb_mcp_trace`，用 `event` 区分（ADR-0017） | 2026-11-26 |
| 漏斗口径 | 连接 = `initialize` 成功数；列工具 = `tools/list` 成功数；实际调用 = `call` 的 ok+error；拒绝不计入调用 | 2026-11-26 |
| 列表接口默认事件 | `event=call`，保持既有页面与筛选语义 | 2026-11-26 |

## 11. 待评审事项

- 本规格是否可进入 RED。
- spool 路径是否按 §4.2 的优先级；生产需在 `env.kb` 中确认 `MEMHUB_DATA_DIR` 或 `MEMHUB_KB_TRACE_SPOOL` 可写。
