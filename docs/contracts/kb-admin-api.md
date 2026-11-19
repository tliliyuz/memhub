# 知识库管理 API（kb-api）

> 版本: 0.1
> 适用范围：本地管理台（`memhub kb`）的 HTTP 接口——列表、详情、新增、编辑、废弃、归档删除、回收站、边编辑、审计、投影重建。
> 不负责：采集入口（见 [ingest-api.md](ingest-api.md)）、MCP 工具（见 [mcp-tools.md](mcp-tools.md)）、节点字段枚举（见 [node-schema.md](node-schema.md)）。

## 1. 定位

- **只绑回环地址、无鉴权**：kb-api 与 worker、collector、浏览器在同一台机器上；公网入口（如果将来有）由 nginx + oauth2-proxy 负责，不在本层做会话。
- **markdown 是真源**：所有写操作都落到 `knowledge/` 下的 markdown + `_edges.jsonl`，写完可选触发投影重建（`kg.json`）。API 不直接改投影。
- **单写者假设**：写操作与 worker 的 merge 共用进程间文件锁 `.memhub-write.lock`，同一时刻只有一个写者；锁超过 120s 视为陈旧接管。
- 真源在 git 仓库内时，每次写成功尝试提交一次（非致命：提交失败不影响写操作返回）。

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
| `1012` KB_INVALID | 400 / 422 | 请求字段非法、frontmatter 校验失败（`data.errors` 给出 `loc/msg/type`） |
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
| POST | `/api/v1/kb/nodes/{node_id}/deprecate` | `{superseded_by, reason, actor}`：tier → `deprecated`、写 `superseded_by`、正文追加 `## 废弃说明`；不删文件 |
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
- `tier=deprecated` 必须同时给 `superseded_by`（走 deprecate 接口更合适）。
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
| GET | `/api/v1/kb/trash?limit=` | `{items:[{id, title, kind, project, deleted_at, reason, actor, trash}], total}`，新的在前 |
| POST | `/api/v1/kb/trash/restore` | `{"trash":"<时间戳>/<node_id>"}` → `{id, revision, commit}`；目标已重新存在 → 409/`1010`，路径非法 → `1012` |

删除的边不会随恢复回来；需要重新编辑。

### 4.5 检索与审计

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/search?q=&project=&kinds=a,b&tier=all&limit=` | `{results:[{id, kind, tier, title, score, matched, snippet}]}` |
| GET | `/api/v1/kb/audit?limit=&offset=` | `{issues:[{type, target, …}], total, offset, limit}` |

审计 issue 类型：`contradiction`（矛盾）、`broken_link`（断链 / 未解析边）、`orphan`（孤立节点）、`low_confidence`（置信度低）、`stale`（长期未更新）。修复入口都是节点编辑。

### 4.6 投影

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/v1/kb/projection`、`/api/v1/kb/rebuild` | `{running, started_at, finished_at, error, nodes, edges, unresolved_edges, graph, graph_mtime, stale}`；冷启动时节点/边数直接读现有 `kg.json` |
| POST | `/api/v1/kb/rebuild` | 同步重建；返回同上的状态；失败 500/`2001` + `data` 带状态 |

- 写操作后默认 1.5s 防抖重建一次（`MEMHUB_KB_AUTO_REBUILD=0` 关闭）。
- 设置了 `MEMHUB_KB_GRAPH_PORT` 时，重建完成后由 kb-api 重启托管的 explorer 子进程（explorer 只在启动时读 `kg.json`）。

### 4.7 前端

`MEMHUB_KB_WEB_DIST` 指向打包产物时，非 `/api` 路径回退到 `index.html`（SPA）；`/api/...` 未知路径返回 404 + `1011`。

## 5. 不变式

1. 任何写操作都不直接改 `kg.json`；投影永远可由真源重建。
2. 删除只做归档（`_trash/`），不 `unlink` 真源；需要物理清理时人工处理 `_trash/`。
3. 一次写操作 = 一次锁持有；锁内不做 git 提交以外的长任务（git 超时 60s，失败不阻塞返回）。
4. `git add` 只针对真源目录，并排除 `.memhub-write.lock`（运行时状态不进历史）。
