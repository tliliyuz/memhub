# 知识节点 Schema

> 版本: 0.1（草案，待与客户端/服务器侧评审）
> 适用范围：知识库真源（markdown frontmatter）、API 返回、MCP 输出、图谱投影共用同一套枚举。

## 1. 真源形态

每条知识是一个 markdown 文件，路径即 id：

```
knowledge/<project>/<kind>/<slug>.md
例：knowledge/memory-hub/concept/memory-hub.md
    knowledge/memory-hub/pitfall/no-proxy-ipv6-httpx.md
```

slug：小写、空格转连字符、保留中文。

## 2. frontmatter

```yaml
---
id: memory-hub                     # 全局唯一，等于相对路径去扩展名，可重命名后保持稳定
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
created_at: 2026-11-18T10:02:00Z
updated_at: 2026-11-18T10:02:00Z
valid_from: null                   # 可选，时间语义
valid_until: null
supersedes: []                     # 取代了哪些 id
superseded_by: null
---
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

关系存放在独立文件 `knowledge/<project>/_edges.jsonl`（一行一条），或由正文 `[[wikilink]]` 解析生成。

```jsonl
{"source":"memory-hub","predicate":"manages","target":"wiki","source_doc":"memory-hub/concept/memory-hub.md"}
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
- 永不硬删；废弃用 `tier: deprecated` + `superseded_by`。
- 每次修改必须更新 `updated_at`，并在文件末尾追加 `## Change Log` 条目（谁、为什么、证据）。

## 6. 投影

| 投影 | 来源 | 用途 |
|---|---|---|
| `kg.json` | frontmatter + edges | MCP 图遍历、explorer 可视化 |
| `vector/` | title + 正文 + tags | 语义检索 |
| `fts.db` | 正文（中文分词） | 关键词检索 |

投影可随时丢弃重建；真源只有 markdown。