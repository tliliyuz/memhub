# 知识节点 Schema

> 版本: 0.5（ADR-0014：写入即 canonical，`candidate` 无写入路径，检索默认排除 `deprecated`；真源为 PostgreSQL `kb_*`，ADR-0013）
> 适用范围：知识库真源（PG `kb_nodes`）、API 返回、MCP 输出、图谱查询共用同一套枚举。
> 不负责：检索与工具接口（见 [mcp-tools.md](mcp-tools.md)）、采集协议（见 [ingest-api.md](ingest-api.md)）。

## 1. 真源形态

每条知识是 PG `kb_nodes` 的一行，`id` 为 `<project>/<kind>/<slug>`：

```
kb_nodes.id: memory-hub/concept/memory-hub
             memory-hub/pitfall/no-proxy-ipv6-httpx
```

slug：小写、空格转连字符、保留中文。

markdown 文件（`knowledge/<project>/<kind>/<slug>.md`）只在一次性迁移时作为来源读取，迁移校验通过后从服务器删除；仓库只保留测试夹具。文件路径与 `id` 的对应关系（相对路径去扩展名）仅用于迁移映射。

## 2. 节点字段

逻辑形状如下（`kb_nodes` 列与 API/MCP 输出同名；`body` 单独存正文）：

```yaml
id: memory-hub                     # 全局唯一，<project>/<kind>/<slug>，可重命名后保持稳定
kind: entity                       # 必填，见枚举
entity_kind: service               # kind=entity 时必填
title: Memory Hub
tier: canonical                    # canonical | deprecated（candidate 仅保留枚举，无写入路径）
confidence: 0.86                   # 0-1，抽取或人工确认时写入
project: memory-hub                # 归属项目/库
tags: [mcp, panel]
source:                            # 溯源，可多条
  - type: session                  # session | wiki | upload | manual
    ref: claude-code/2026-11-18/abc123#L420-L455
    device: applesay-win-01
    captured_at: 2026-11-18T10:00:00Z
revision: 9f2c1a3b4d5e6f70         # 16 位小写 hex，每次写入重算
created_at: 2026-11-18T10:02:00Z
updated_at: 2026-11-18T10:02:00Z
valid_from: null                   # 可选，时间语义
valid_until: null
supersedes: []                     # 取代了哪些 id
superseded_by: null                # 被谁取代；没有替代节点时留空
deprecated_reason: null            # tier=deprecated 且无替代节点时写原因
```

### 时间语义

`created_at` / `updated_at` / `valid_from` / `valid_until` / `occurred_at` / `decided_at`
一律 UTC：写入时 naive 时间（如裸日期 `2026-11-21`）按 UTC 补齐，带偏移的换算到
UTC 后存储；API 与 MCP 输出统一为 `Z` 后缀。这样同一输入不会因会话时区不同而落成
不同时刻（生产库会话时区是 +08）。`source[].captured_at` 以原始文本存 JSONB，
保留调用方给的偏移，不在这条归一范围内。

## 3. kind 枚举

| kind | 含义 | 必填字段 |
|---|---|---|
| `entity` | 有身份的对象 | `entity_kind` |
| `fact` | 关于实体的断言 | — |
| `decision` | 决策 + 理由 + 备选 | `decided_at`（可空） |
| `procedure` | 可复用、已验证的方法 | — |
| `pitfall` | 症状 + 根因 + 解法 | `symptom`（正文约定） |
| `preference` | 用户工作偏好/约束 | — |
| `event` | 有时间点的事件 | `occurred_at` |
| `question` | 未决问题 | `status: open\|resolved` |

`entity_kind` 枚举：
`service | component | concept | tool | person | team | project | external_system | config | other`

## 4. 关系（边）枚举

关系存放在 PG `kb_edges`（`project` 归属、`source`/`target`/`predicate`/`source_doc`），由提炼管线写入，`[[wikilink]]` 解析仍可生成。迁移期 markdown 的 `knowledge/<project>/_edges.jsonl`（一行一条）只作一次性来源。

```json
{"source":"memory-hub","predicate":"manages","target":"wiki","source_doc":"memory-hub/concept/memory-hub"}
```

| predicate | 语义 | 典型两端 |
|---|---|---|
| `part_of` | 组成 | entity → entity |
| `depends_on` | 依赖 | entity → entity |
| `exposes` | 对外暴露 | service → config/interface |
| `runs_on` | 运行于 | service → external_system |
| `about` | 论述对象 | fact/pitfall/decision → entity |
| `resolved_by` | 由…解决 | pitfall → procedure |
| `supersedes` | 取代 | any → any |
| `contradicts` | 冲突（待裁决） | fact → fact |
| `evidenced_by` | 证据 | any → source 片段 |
| `related_to` | 兜底弱关系（LLM 不确定时） | any → any |

**约束**：`contradicts` 必须由治理流程裁决，不得自动合并。

## 5. tier 与治理

| tier | 含义 | 谁可写 |
|---|---|---|
| `canonical` | 有效知识；所有新节点默认写入此层 | 提炼管线 / MCP 写工具 / 管理台 |
| `candidate` | 历史存量取值，枚举保留，**已无写入路径** | —— |
| `deprecated` | 已过时（保留，不删除） | 管理台 / MCP 废弃工具 |

规则（ADR-0014）：
- 写入即生效：worker 抽取、MCP 写入与管理台新建一律落 `canonical`，不再经过「候选转正」。存量 `candidate` 由一次性数据迁移转 `canonical`，修订历史记 `actor=system`、`reason=ADR-0014`。
- 检索默认排除 `deprecated`，即默认返回全部有效节点；显式要求时才包含 `deprecated`（见 [mcp-tools.md](mcp-tools.md) §1）。
- 永不硬删；废弃用 `tier: deprecated`，并至少给出 `superseded_by`（有替代节点）或 `deprecated_reason`（结论被证伪、无替代物）。
- 每次修改必须更新 `updated_at`，并在同一事务向 `kb_node_revisions` 追加一条修订（含 `before`/`after` 完整快照，`actor` 与 `reason`），取代原 markdown 的 `## Change Log` 与 git 提交。
- 节点级写权限：MCP 的更新与废弃工具只允许修改「创建者 `actor` 与调用方一致」的节点，创建者取 `kb_node_revisions` 中该节点最早一条修订的 `actor`（见 [mcp-tools.md](mcp-tools.md) §1.2）。管理台不受此限。

## 6. 投影

真源只有 PG `kb_*` 表：图谱（管理台图谱页、`/api/v1/kb/graph`、MCP 图遍历）与检索都直接查询，不再生成 `kg.json` 等文件投影。关键词检索在 SQL 侧过滤候选集后由应用层 BM25 排序（`matched` 为 `"bm25"`）。向量检索按 ADR-0007 另案推进。
