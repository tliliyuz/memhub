# 知识库管理 API（kb-api）

> 版本: 0.3
> 适用范围：本地管理台（`memhub kb`）的 HTTP 接口——列表、详情、新增、编辑、废弃、归档删除、回收站、边编辑、审计、上传入队、投影重建、当前登录身份。
> 不负责：采集入口（见 [ingest-api.md](ingest-api.md)）、MCP 工具（见 [mcp-tools.md](mcp-tools.md)）、节点字段枚举（见 [node-schema.md](node-schema.md)）。

## 1. 定位

- **只绑回环地址、无鉴权**：kb-api 与 worker、collector、浏览器在同一台机器上；公网入口（如果将来有）由 nginx + oauth2-proxy 负责，不在本层做会话。
- **markdown 是真源**：所有写操作都落到 `knowledge/` 下的 markdown + `_edges.jsonl`，写完可选触发投影重建（`kg.json`）。API 不直接改投影。
- **单机写入互斥**：管理端、worker 合并、CLI 合并与投影发布共用 OS 持有的 `.memhub-write-v2.lock`。进程退出释放锁；不要删除或替换锁文件。归档中的库禁止普通写入，worker 保留队列文件并推迟处理，不计失败。
- 真源在 git 仓库内时，每次写成功尝试提交一次（非致命：提交失败不影响写操作返回）。
- **上传是唯一不直接写真源的入口**：它把文件送进提炼队列（raw_store），由 worker 异步提炼成 markdown；接口返回只代表「已收到并排队」。

启动：

```bash
memhub kb --knowledge-dir ./knowledge --graph-out kb/kg.json \
          --web-dist web/dist --spawn-graph --graph-port 8703  # 端口默认 8701
```

## 2. 错误信封

非 2xx 一律返回：

```json
{ "code": 1010, "message": "节点已被修改，请刷新后重试", "data": { "expected": "…", "actual": "…" } }
```

| code | HTTP | 含义 |
|:---|:---|:---|
| `1010` KB_CONFLICT | 409 | 修订号不匹配（乐观并发） |
| `1011` KB_NOT_FOUND | 404 | 节点 / 回收站条目 / 接口不存在 |
| `1012` KB_INVALID | 400 / 422 | 请求字段非法、frontmatter 校验失败（`data.errors` 给出 `loc/msg/type`）；上传整批无可用文件时 `data.rejected` 给出逐文件原因 |
| `1013` KB_QUEUE_FULL | 503 | 提炼队列已满（`data:{used,limit,incoming}`），稍后重试；上传专用，与采集端的 `1008` 语义相同但属于本 API 的错误码区间 |
| `2001` INTERNAL | 500 | 投影重建等内部错误 |

请求体一律 `extra="forbid"`：多传字段返回 422 + `1012`。

## 3. 并发控制

- 每个节点的修订号 = 该文件字节的 `sha256[:16]`（内容寻址）。读取时返回 `revision`。
- 更新/删除必须带 `expected_revision`（更新在 body，删除在 query）。不匹配 → 409/`1010`，客户端刷新后重试。
- 保存成功返回新 `revision`；同一内容重写会产生新的 `updated_at`，因此修订号也会变。

## 4. 接口

### 4.1 健康与统计

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/healthz`、`/api/v1/kb/healthz` | `{ok, knowledge_dir, nodes, projection}` |
| GET | `/api/v1/kb/stats` | `{nodes, edges, unresolved_edges, orphans, by_kind, by_tier, by_project}` |

### 4.2 节点

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/nodes` | query：`project`、`kind`、`tier`、`q`、`tag`、`limit`(≤500)、`offset`；返回 `{items, total, offset, limit}`，按 `updated_at` 倒序 |
| POST | `/api/v1/kb/nodes` | 201；body 见 §4.2.1；返回 `{id, revision, commit, node}` |
| GET | `/api/v1/kb/nodes/{node_id}` | `id` 可含 `/`（`{node_id:path}`）；返回 `{id, revision, frontmatter, body, truncated, edges:{out,in}, source}` |
| PUT | `/api/v1/kb/nodes/{node_id}` | 部分更新；必填 `expected_revision`，其余字段同创建（`title/body/tags/tier/confidence/status/valid_*/occurred_at/decided_at/superseded_by`） |
| POST | `/api/v1/kb/nodes/{node_id}/deprecate` | `{superseded_by, reason, actor}`：tier → `deprecated`、写 `superseded_by`、正文追加 `## 废弃说明`；不删文件。管理台这条路径仍要求给出替代节点；只记原因的废弃目前只经 MCP 的 `kb_deprecate` 提供 |
| DELETE | `/api/v1/kb/nodes/{node_id}?revision=&reason=&actor=` | 移入 `_trash/<UTC 时间戳>/<node_id>.md` + `.meta.json`，并移除相连边；返回 `{id, trash, removed_edges, commit}` |

#### 4.2.1 创建 body

```json
{
  "kind": "fact",
  "title": "HTTPX trust_env 导致代理 502",
  "body": "先看 trust_env。",
  "project": "memhub",
  "tier": "candidate",
  "tags": ["httpx"],
  "entity_kind": null,
  "confidence": 0.8,
  "slug": null,
  "supersedes": [],
  "actor": "ui"
}
```

- `kind` 与 `tier` 取 [node-schema.md](node-schema.md) 的枚举；`kind=entity` 必须给 `entity_kind`，否则 `1012`。
- `tier=deprecated` 必须给 `superseded_by` 或 `deprecated_reason` 至少一项（走 deprecate 接口更合适）：有替代节点就指向它，结论被证伪则只记原因。管理台 `PUT` 与 `/deprecate` 目前只写 `superseded_by`，`deprecated_reason` 由 MCP 写工具写入。
- `slug` 缺省由标题生成 kebab-case；中文标题生成不出 slug 时回退 `n-<随机 4 字节 hex>`。同目录重名 → `1012`。
- 写入路径：`<knowledge>/<project>/<kind>/<slug>.md`。

### 4.3 边

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| PUT | `/api/v1/kb/nodes/{node_id}/edges` | **替换**该节点全部出边：`{"edges":[{"predicate":"about","target":"memhub/fact/x"}]}` |

- 目标可以是完整 id，也可以是唯一 slug；解析不到的目标原样保留（投影时报 `unresolved`）。
- 只允许改「以该节点为 source」的边；其他节点的边保持原样。
- 路由顺序注意：`/edges` 必须在 `PUT /nodes/{node_id:path}` 之前注册，否则贪婪匹配会把 `edges` 吃进 id。

### 4.4 回收站

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/trash?limit=&offset=&project=&q=` | `{items:[{id, title, kind, project, deleted_at, reason, actor, trash}], total, offset, total_all}`，新的在前 |
| POST | `/api/v1/kb/trash/restore` | `{"trash":"<时间戳>/<node_id>"}` → `{id, revision, commit}`；目标已重新存在 → 409/`1010`，路径非法 → `1012` |

- `limit` 1–500（默认 100），`offset` ≥ 0；`project` 按库过滤，`q` 匹配标题或 id（不区分大小写）。
- `total` 是**过滤后**总数，`total_all` 是过滤前总数——页面要显示「共 N 条（全部 M 条）」时需要两个值。
- 排序仍是归档路径字符串（时间戳 + id）倒序，同一时间戳内按 id 倒序，不按 `deleted_at` 排序。

删除的边不会随恢复回来；需要重新编辑。

### 4.5 检索与审计

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/search?q=&project=&kinds=a,b&tier=all&limit=` | `{results:[{id, kind, tier, title, score, matched, snippet}]}` |
| GET | `/api/v1/kb/audit?limit=&offset=` | `{issues:[{type, target, …}], total, offset, limit}` |

审计 issue 类型：`contradiction`（矛盾）、`broken_link`（断链 / 未解析边）、`orphan`（孤立节点）、`low_confidence`（置信度低）、`stale`（长期未更新）。修复入口都是节点编辑。

### 4.6 知识库（project）与子图

真源按 `<knowledge>/<project>/` 隔离，**project 就是知识库**：`sdp-tag`、`memory-hub`
各自一批节点，边文件也是每个库一份（`<project>/_edges.jsonl`），天然不会混库。

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/projects` | `{items:[{id, name, description, nodes, edges, updated_at, created_at}], total}`；扫描真源一级目录，并合并 `.kbs.json` 里的显示名/描述 |
| POST | `/api/v1/kb/projects` | 201；`{id, name?, description?}`；`id` 必须匹配 `^[a-z0-9][a-z0-9._-]{0,63}$` 且目录不存在，否则 `1012` |
| PATCH | `/api/v1/kb/projects/{project}` | `{name?, description?}`；只改 `.kbs.json` 元数据，不动 markdown；库不存在 → `1011` |
| DELETE | `/api/v1/kb/projects/{project}?actor=` | 整库归档；返回 `{id, archive_id, archived_count, removed_edges, commit}`；库不存在 → `1011` |
| GET | `/api/v1/kb/trash/projects` | `{items, total}`；每项含 `archive_id, id, name, deleted_at, archived_count, removed_edges` |
| POST | `/api/v1/kb/trash/projects/restore` | `{archive_id}`；返回 `{id, archive_id, restored_count, restored_edges, commit}` |
| GET | `/api/v1/kb/graph?project=` | `{project, nodes:[{id, title, kind, tier, entity_kind, tags, degree, updated_at}], edges:[{source, target, predicate}], unresolved_edges}` |

- `graph` 只返回该库自己的节点；边端点按完整 id 或「库内唯一 slug」解析，解析不到的计入 `unresolved_edges`，不影响其他边。
- `degree` 双向计数，节点按 `(-degree, id)` 排序，方便画图时先看枢纽。
- 这个接口直接读 markdown 真源，**不依赖 `kg.json` 投影**；管理台的图谱页就用它（不再内联 semantica explorer）。
- `.kbs.json` 存库的显示名和描述等登记信息，写操作同样走 `.memhub-write-v2.lock`。

#### 4.6.1 归档删除一个知识库

整库删除是**可恢复归档**。在共享写锁内验证库目录、登记信息和关系，先保存带校验的快照，再从活跃真源移除项目。快照保存原始 Markdown、完整库登记信息（或未登记状态）、库内边和受影响的跨库边；空库也生成归档。快照不参与节点和边扫描。

恢复到原项目 ID。库已存在、外部库或应恢复的端点已不存在、关系有冲突、短别名会改变指向、路径异常或快照损坏时返回 `409/1010`，不覆盖已有资源。跨库关系合并到当前文件，保留归档期间无关修改。

这不是跨文件事务。持久记录操作意图；异常时保留快照，若操作未完成，暂停普通写入及投影重建，待本机恢复命令核对并续做后再开放。成功归档或恢复会使投影重新生成。

历史单节点归档仍使用原有 `/trash` 和 `/trash/restore`，不补造历史上未归档的关系。

#### 4.6.2 当前登录身份

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/me` | `{authenticated, user, avatar_url}` |

- 公网入口由 nginx + oauth2-proxy 鉴权（见部署配置）：`--set-xauthrequest=true` 让认证判决带回 `X-Auth-Request-User`，nginx 用 `auth_request_set` 取出并作为 `X-Memhub-User` 透传给 kb-api。GitHub 的登录名在 `User` 头，`Preferred-Username` 对 GitHub 为空，不要用后者。
- `user` 取自 `X-Memhub-User`；`avatar_url` 指向该登录名的 GitHub 头像，请求结果不缓存。本机直连（没有网关）时 `authenticated=false`、`user=null`，前端据此显示「本地直连」并隐藏退出登录。
- 退出登录不走本 API：前端跳 `/oauth2/sign_out?rd=/oauth2/sign_in`，由网关清会话 cookie 后停留在登录页，不退出 GitHub 本身。

### 4.7 上传（送进提炼队列）

把文件直接投进提炼队列，与采集器推送共用同一套 raw_store 布局与配额；不需要
device token、游标与批次幂等。需要 `MEMHUB_DATA_DIR`（或 `memhub kb --data-dir`），
未配置时两个接口都返回 503/`2001`，其余接口不受影响。

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| POST | `/api/v1/kb/uploads` | `multipart/form-data`：`project`（知识库 id）+ `files`（可多个）；201 返回 `{batch_id, project, accepted:[{name, sha256, chars}], rejected:[{name, reason}], queued:true}` |
| GET | `/api/v1/kb/uploads/{batch_id}` | `{batch_id, project, created_at, total, counts:{queued,processed,failed,missing}, files:[{name, sha256, status, attempts?}]}` |

- 允许后缀 `.md` / `.txt` / `.jsonl`，UTF-8，单文件 ≤60000 字符，单批 ≤20 个文件；`project` 必须匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`，不得为 `auto`，且必须是**已登记的活动知识库**（否则返回 404/`1011`；暂无法核验返回 503/`2001`）。管理台鉴权不变，不使用设备授权。
- 单个文件不合规进 `rejected`（`unsupported_type` / `not_utf8` / `empty` / `too_large` / `invalid_name`），其余文件照常接收；整批没有可接受的 → 422/`1012`，`data.rejected` 给出原因。
- 内容按库和 sha256 寻址：已有相容的队列记录仍在原始、已处理或待复核目录时，不为重复上传新增原始副本。记录清理后不保证去重。
- 落盘：`<DATA_DIR>/raw_store/kb-console/<project>/<sha[:2]>/<sha>.json`，由服务端标记 `producer=console`、`source_type=docs`。worker 只接受确切的管理台身份及活动目标，按 docs profile 提炼；采集设备不能使用该保留身份。批次清单在 `<DATA_DIR>/uploads/<batch_id>.json`，`uploads/` 不在 worker 扫描范围内。
- 状态逐文件推导，与 worker 的搬运动作一致：`processed_raw/<rel>` → `processed`；`pending_review/<rel>` → `failed`；`state/failures.json[rel]` 有计数 → `failed`（带 `attempts`）；仍在 raw_store → `queued`。worker 只在时间窗口内搬运，白天长时间 `queued` 属正常排队，不是故障。
- 队列总量受 `MEMHUB_QUEUE_MAX_BYTES` 约束，超限 503/`1013`。kb-api 与 ingest-api 是两个进程、各持一份 30 秒刷新的用量缓存，跨进程并发推送/上传可能短暂超出上限（容忍一个刷新窗口）。
- 批次 id 非法或清单不存在 → 404/`1011`。

### 4.8 投影

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/projection`、`/api/v1/kb/rebuild` | `{running, started_at, finished_at, error, nodes, edges, unresolved_edges, graph, graph_mtime, stale}`；冷启动时节点/边数直接读现有 `kg.json` |
| POST | `/api/v1/kb/rebuild` | 同步重建；返回同上的状态；失败 500/`2001` + `data` 带状态 |

- 写操作后默认 1.5s 防抖重建一次（`MEMHUB_KB_AUTO_REBUILD=0` 关闭）。
- 设置了 `MEMHUB_KB_GRAPH_PORT` 时，重建完成后由 kb-api 重启托管的 explorer 子进程（explorer 只在启动时读 `kg.json`）。

### 4.9 前端

`MEMHUB_KB_WEB_DIST` 指向打包产物时，非 `/api` 路径回退到 `index.html`（SPA）；`/api/...` 未知路径返回 404 + `1011`。

## 5. 不变式

1. 任何写操作都不直接改 `kg.json`；投影永远可由真源重建。
2. 删除只做归档（`_trash/`），不 `unlink` 真源；需要物理清理时人工处理 `_trash/`。
3. 一次写操作 = 一次锁持有；锁内不做 git 提交以外的长任务（git 超时 60s，失败不阻塞返回）。
4. `git add` 只针对真源目录，并排除 `.memhub-write.lock`（运行时状态不进历史）。
