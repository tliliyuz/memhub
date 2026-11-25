# 知识节点 Schema

> 版本: 0.2（真源改为 PostgreSQL `kb_*`，ADR-0013）
> 适用范围：知识库真源（PG `kb_nodes`）、API 返回、MCP 输出、图谱投影共用同一套枚举。
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
tier: candidate                    # candidate | canonical | deprecated
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
| `candidate` | 自动抽取，未经确认 | 提炼管线 / 治理 agent 直写 |
| `canonical` | 已确认 | 治理 agent 提案 + 用户确认；或历史导入后人工确认 |
| `deprecated` | 已过时（保留，不删除） | 治理 agent |

规则：
- 检索默认只返回 `canonical`；无命中时回退 `candidate` 并标注。
- 永不硬删；废弃用 `tier: deprecated`，并至少给出 `superseded_by`（有替代节点）或 `deprecated_reason`（结论被证伪、无替代物）。
- 每次修改必须更新 `updated_at`，并在同一事务向 `kb_node_revisions` 追加一条修订（含 `before`/`after` 完整快照，`actor` 与 `reason`），取代原 markdown 的 `## Change Log` 与 git 提交。候选转正、tier 审批流仍由治理流程另行推进。

## 6. 投影

| 投影 | 来源 | 用途 |
|---|---|---|
| `kg.json` | `kb_nodes` + `kb_edges` | 只供旧 explorer 可视化与 `/api/v1/kb/projection` 状态展示；MCP 图遍历与管理台图谱直接查 PG，不读它 |

关键词检索不再依赖 `fts.db` 投影：kb-api 在 SQL 侧过滤候选集后用应用层 BM25 排序（`matched` 为 `"bm25"`）。向量投影与混合检索按 ADR-0007 另案推进。

投影可随时丢弃重建；真源只有 PG `kb_*` 表。
