# 采集端 ↔ 云端 API 契约

> 版本: 0.6
> 基址：`https://memhub.work/api/v1`
> 传输：HTTPS + JSON；大批量用 `application/gzip`（见 §5）。
> 客户端：agent-console 内置 headless collector。服务端：本仓库。
> 适用范围：采集端与云端之间的推送、游标、心跳、鉴权、错误码与限流契约。
> 不负责：节点字段枚举（见 [node-schema.md](node-schema.md)）、源注册表（见 [source-registry.md](source-registry.md)）、服务端实现（见 [architecture.md](../architecture.md)）。

## 0. 通用约定

### 统一响应包

```json
{ "code": 0, "message": "ok", "data": { } }
```

- **`code` 是本 API 的业务码，不是 HTTP 状态码。** 面板旧接口的 `{code: 409, message: "KEY_LIMIT_EXCEEDED"}` 是另一套信封，不要复用它的解析器。
- HTTP 状态码仍表达传输层语义（401/403/429/5xx）。
- 所有时间为 RFC3339 UTC。

### 鉴权

```
Authorization: Bearer <device_token>
```

**device_token ≠ 用户 user_key。** 后者同时授权 `meta/*` 与 `knowledge/*`，且每用户只有 20 把、最后一把不可吊销——采集器绝不能持有它。

注册流程（两段式，**不走 PKCE**）：

1. **桌面端**用它自己已有的凭据（门户会话或凭据库里的 `user_key`）调用：
   `POST /devices/register {device_id?, name, platform}` → `{device_id, device_token, created_at}`
   - 生产必须带 `Authorization: Bearer <user_key>`（注册是用户态操作，`device_token` 本身不能注册设备）；缺失返回 `401 {code:1001}`。dev stub 未强制，仅便于本地联调。
   - `device_id` 由客户端首次运行生成 **UUID v4** 并持久化；生产按**必填**处理，缺失或格式不符返回 `400 {code:1002}`。服务端自动生成只保留在 dev stub（真客户端不应依赖）。
   - `device_token` 写入**操作系统凭据库**（Windows Credential Manager / macOS Keychain / libsecret），**不落任何 json 文件**。
   - PKCE 留在它本来该在的位置（桌面端引导自己的 `user_key`），不为设备注册再造 loopback 回调。
2. **采集器**只从凭据库读 `device_token`，走 `Authorization: Bearer`。

作用域：

- `device_token` 仅允许 `/ingest/*`。访问 `/api/v1/meta/*`、`/api/v1/knowledge/*` 必须返回 `403 {code:1009}`（scope 不足）。
- 一个用户可注册多设备；每个 device_id 一枚 token。
- 吊销：`POST /devices/revoke {device_id}`（桌面端/用户态）。吊销后采集器下次请求得 `401 {code:1001}`，必须**停推 + 心跳上报 + 本地告警**，不得静默重试。
- 轮换：`POST /devices/refresh`，旧 token 宽限 10 分钟。
- 重复注册（幂等）：同一 `device_id` 在**未吊销**状态下重复调用 `/devices/register`，返回同一枚仍有效的 token，不旋转——provision 失败后整段重试安全，客户端不依赖“重注册换新 token”。被吊销后重新注册视为重新启用：签发新 token，旧 token 失效，采集器在桌面重新 provision 后自动恢复，无需重启。自动轮换只由 `/devices/refresh` 触发，客户端不自动调用。
- 采集器拿到 `401 {code:1001}`（吊销/无效 token）必须停推该链路并本地告警，不得静默重试；重新 provision 产生新 token 后再继续。

**所有端点（含 GET）都要求 Bearer**；`device_id` 可以出现在 query，但服务端必须校验 `token.device_id == 请求中的 device_id`，不一致返回 `403`。

### 限流与退避

| 端点 | 限额 |
|---|---|
| `/ingest/*` | 30 r/min / device，单请求体 ≤ 16MiB |
| `/devices/*` | 10 r/min / device |

`429` 响应带 `Retry-After`。

客户端退避：基准 `1,2,4,8,16,32,60` 秒封顶，**每档 ±20% 抖动**（否则服务端重启后所有设备会同步回到阶梯起点形成风暴）；成功一次后重置。

连续失败 1 小时进入「降级」（间隔 15 分钟）并写本地告警。**降级不等于丢弃**：本地队列到达上限时停止采新、心跳上报 `paused`，不得静默丢弃增量。

### 幂等

- 每个推送批次带 `batch_id`（客户端生成 uuid v4）。服务端按 `(device_id, batch_id)` 去重，**去重窗口 24 小时**。
- 窗口内重放必须通过当前目标校验，且与原批次绑定同一目标，才返回 `200` 和上次结果（`data.replayed:true`），不会追加新文件。旧结果没有可验证的目标绑定或目标不一致时返回 `400/1003`。游标冲突仍为 `409/1004`。
- 窗口外按新批次处理；同设备、同源下仍存在于原始、已处理或待复核队列的同哈希记录不得改投。此检查不覆盖已经清理的记录；不承诺永久保留批次与目标的绑定。

## 1. 游标

### `GET /ingest/cursor?device_id=<id>&source_id=<id>`

（需 Bearer；token.device_id 必须等于 query 的 device_id）

```json
{ "code": 0, "message": "ok", "data": {
    "source_id": "cc-sessions",
    "source_rev": 3,
    "cursor": { "files": 37, "bytes": 10485760, "last_at": "2026-11-18T09:58:00Z" },
    "files": [
      { "path": "projects/D--workplace-export-memhub/abc.jsonl",
        "offset": 182344, "size": 182344, "mtime": "2026-11-18T09:57:12Z" }
    ],
    "updated_at": "2026-11-18T09:58:00Z"
  } }
```

说明：
- `offset` 为**文件字节偏移**，客户端从 `offset` 处继续读。
- 每个文件必须同时带 `size` 与 `mtime`。**单靠 offset 不可靠**：文件被截断、轮转、原地重写后 offset 会指向不存在的位置。
- 客户端规则：本地 `size < cursor.offset`（或 `mtime` 变小）时判定为「文件被替换」，该文件**从 0 重扫**，并在下一次推送里带 `"source_rev": 新值`。
- 服务端收到比当前更大的 `source_rev` 时，允许该源从 0 开始，**不**返回 1004；小于等于当前值且 offset 回退才返回 1004。
- `files` 可能很大；服务端按 `limit=500` 分页，`next_page_token` 放在 `data` 内。
- 未注册的 source 返回空游标（`files: []`, `source_rev: 0`），不算错误。

## 2. 推送

### `POST /ingest/raw`

请求（`content-type: application/json`）：

```json
{
  "batch_id": "9f1c...",
  "device_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
  "source_id": "cc-sessions",
  "source_type": "sessions",
  "project": "sdp-tag",
  "source_rev": 0,
  "cursor_before": { "files": 37, "bytes": 10485760 },
  "cursor_after":  { "files": 39, "bytes": 10616832 },
  "files": [
    {
      "path": "projects/D--workplace-export-memhub/abc.jsonl",
      "from_offset": 0,
      "to_offset": 182344,
      "mtime": "2026-11-18T09:57:12Z",
      "sha256": "…",
      "content": "…"
    }
  ]
}
```

字段约束：

| 字段 | 说明 |
|---|---|
| `content` | 只允许 **纯文本** 容器（`.jsonl` / `.md` / `.txt` / `.log`）。二进制（图片、pdf、sqlite）一律不上传，客户端直接跳过并在返回值里报 `skipped:[...]`。 |
| `from_offset/to_offset` | 用于服务端拼接；`from_offset` 必须 ≥ 服务端已知 offset，否则返回 `409 {code:1004, data:{expected_offset}}`，客户端回退。 |
| `sha256` | 原文片段哈希，服务端用于二次去重。 |
| `cursor_before` / `cursor_after` | **仅诊断**，服务端不校验，也不据此产生 1004。游标以每条文件的 `from_offset` 为准。 |
| `project` | 必须是用户选定的显式知识库 ID（`^[a-z0-9][a-z0-9._-]{0,63}$`，不允许 `auto`，不修剪空白）。目标必须已在管理台登记且当前活动。不推断目标，不用 `source_id` 兜底，不自动建库。 |

缺失、空值、非字符串、格式错误、未登记、不活动的目标统一返回 HTTP `400`、`code:1003`，用 `data.reason` 区分 `missing` / `reserved` / `invalid` / `unregistered` / `inactive` / `target_conflict`，不回显目标或披露是否存在；拒绝发生在配额、落盘和游标更新之前，重放也要先通过目标校验。服务暂不能确认登记状态时返回通用 `500/2001`，可重试。目标被拒仅影响该源：保留待发增量，不推进被拒游标，修正目标前不重复推送，不停掉正常的兄弟源。已有同源同哈希内容不能用另一个目标重新提交；同一批次 ID 也不能用于重定向。

服务端游标校验只看两处：`source_rev`（是否允许重扫）与每条文件的 `from_offset`（相对已知 offset 是否回退）。

部分成功：`200` + `data.results[]`；完全失败才用 4xx/5xx。

```json
{ "code": 0, "message": "ok", "data": {
    "batch_id": "9f1c...",
    "replayed": false,
    "accepted": 2, "duplicates": 0, "skipped": [],
    "cursor": { "files": 39, "bytes": 10616832 },
    "queued": true
  } }
```

- `queued: true` 表示已入提炼队列，**不代表**已提炼完。提炼是异步的（见 §4）。

### `POST /ingest/heartbeat`

```json
{ "device_id": "...", "collector_version": "0.1.0",
  "state": "running",
  "queue": { "pending_batches": 0, "pending_bytes": 0, "paused": false },
  "sources": [
    { "source_id": "cc-sessions", "enabled": true, "last_scan_at": "...",
      "pending_bytes": 4096,
      "skipped": { "binary": 3, "reparse_point": 0, "offline": 12, "oversize": 1 } }
  ] }
```

- `state`: `running | degraded | paused | unauthorized`。采集器被吊销/停推时必须显式报 `unauthorized`，不静默。
- `skipped` 计数用于排查「某个目录永远同步不上却不报错」；`offline` 特指 Windows 上带 `FILE_ATTRIBUTE_OFFLINE` 的占位文件。
- 返回 `data.commands[]`：`{"type":"reload_config"}` / `{"type":"pause","until":"..."}` / `{"type":"upgrade","min_version":"..."}`。

### `GET /ingest/projects?device_id=<id>`

桌面端「被采集目录 → 已有知识库」下拉框的数据源：只返回已登记且活动的知识库，完整返回已筛选条目，不分页。只有实施此筛选且推送也实施同一规则时才返回 `writable_only: true`。

```json
{ "code": 0, "message": "ok", "data": {
    "items": [
      { "id": "sdp-tag", "name": "SDP Tag", "description": "标签系统",
        "nodes": 206, "edges": 131, "updated_at": "2026-11-20T01:38:16Z" }
    ],
    "total": 1,
    "writable_only": true
  } }
```

- 鉴权同 `/ingest/raw`（设备 token）。
- 服务暂无法验证列表时返回 `500 {code:2001}`；缺少 `writable_only:true` 的旧服务响应不能用于授权选库。
- 用户选中的 `id` 写回 `sources.json` 的 `sources[].project`；采集器原样放进 `/ingest/raw` 的 `project`。
- 改一个源的 `project` **只影响之后推送的内容**：已提炼的批次按内容寻址落在 `processed_raw/`，不会因为改库名而重跑，也不会搬去新库。

建库不在采集端：客户端只上传，知识库只在管理台 `POST /api/v1/kb/projects` 创建（见 [kb-admin-api.md](kb-admin-api.md)）。`POST /ingest/projects` 已移除，旧客户端调用得到 `404/405`。

### `DELETE /ingest/source/{source_id}?device_id=<id>&purge=true`

用户态调用。`purge=true` 时将该源原始增量标记删除（markdown 真源保留，溯源里该来源标记失效）。

## 3. 错误码

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | ok |
| 1001 | 401 | device token 无效/过期 |
| 1002 | 403 | 设备已吊销 |
| 1003 | 400 | 契约校验失败（字段缺失/类型错）；目标不可用时 `data.reason` 给出细分原因 |
| 1004 | 409 | 游标冲突（`source_rev` 未前进且 offset 回退；带 `expected_offset`） |
| 1005 | 413 | 批次超限（客户端应拆批） |
| 1006 | 422 | 内容无法解析（非文本、编码错） |
| 1007 | 429 | 限流（带 Retry-After） |
| 1008 | 503 | 提炼队列积压，暂缓推送（客户端降级） |
| 1009 | 403 | scope 不足（device_token 访问非 ingest 路由，或 device_id 与 token 不匹配） |
| 2001 | 500 | 服务端内部错误（可重试） |

## 4. 提炼（服务端内部，客户端无需感知）

原始队列记录包含服务端确定的生产者和显式目标。worker 在调用模型前复查来源和当前目标，实际写入时在真源写锁内再次复查。不为旧记录推断或替换目标。明确不合规的原始记录按原因隔离到 `pending_review`，保留原始字节；配置、登记、事务或锁暂不可用时留在队列，不消耗模型重试次数。管理台上传走独立鉴权，但也要求已登记且活动的显式目标。

会话 JSONL 只从可引用的非 `isMeta` 对话文字渲染证据块；摘要、工具输出、无法解析的片段不作为证据，不退回原始 JSONL。提炼只保留具有本窗逐字引用的可复用事实、决策、流程或踩坑；可辨识的跨窗重复只留一份。边须有证据，且两端为无歧义的存活候选。引用匹配证明文本出现过，不证明结论正确。无合格候选时成功处理为零，不写真源；畸形响应按失败重试，超限隔离。候选保留来源引用，不改变节点格式；文档和 wiki 提炼规则不变。

## 5. 大批量（可选）

单批 > 8MiB 时：`content-type: application/gzip`，body 为 gzip 后的 JSON；其它字段不变。服务端上限 16MiB（解压后 64MiB）。

## 6. 版本与兼容

- 路径仍为 `/api/v1`；0.6 移除 `POST /ingest/projects` 与设备—知识库授权文件，`project` 只要求显式、已登记且活动，拒绝原因细化到 `data.reason`。旧客户端调用已删除的建库代理会得到 `404/405`，需要升级到管理台建库；旧版保存的 `auto` 或缺失目标仍在下一次计划运行时被 `400/1003` 拒绝，需升级并修正保存的目标。
- 客户端在 `heartbeat` 上报 `collector_version`；服务端可下发 `upgrade` 命令但不强制。

## 7. 与面板既有接口的边界

- `/api/v1/ingest/*` 是**独立路由**，不复用面板的 raw 上传/转发层（面板 raw 层是给知识库资产用的，`.json` 上传后 `raw/read` 会回 `UNSUPPORTED_FILE_TYPE`）。
- 鉴权、信封、错误码都按本文件；不要套用面板的 `{code: HTTP状态, message: 业务字符串}` 解析器，也不要复制 SSO 换票端点「成功回裸 JSON」的例外形态。
- 面板 `/api/v1/auth/*` 限流 6r/m，采集器一律不调用。
