"""检索组读操作：搜索、读取、邻接、审计列表。

真源是 markdown，这里只读不写、不加缓存。先用标题/标签/正文的关键词打分顶上
真实索引；后续接 FTS 或向量时只替换本模块的实现，MCP 层与工具形状不变
（见 `docs/contracts/mcp-tools.md`）。文件 IO 全程 await，不阻塞事件循环。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from memhub.contract import Kind, NodeFrontmatter, Predicate, Tier
from memhub.kb.bm25 import BM25Okapi, normalize, tokenize


class KnowledgeReader(Protocol):
    @property
    def resolve_short_aliases(self) -> bool: ...

    async def list_ids(self, project: str | None = None) -> list[str]: ...
    async def exists(self, node_id: str) -> bool: ...
    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]: ...
    def edge_lines(self) -> AsyncIterator[str]: ...


MAX_RESULTS = 50
SNIPPET_CHARS = 160
EDGE_LIMIT = 20
READ_MAX_CHARS = 8192
STALE_DAYS = 180
STALE_REFS = 3
TIERS = {"canonical", "candidate", "all"}


class QueryError(Exception):
    """调用参数不合法（MCP 错误码 3004）。"""

    code = 3004


class NotFound(QueryError):
    """节点不存在（MCP 错误码 3001）。"""

    code = 3001


async def records(store: KnowledgeReader, project: str | None = None) -> list[NodeRecord]:
    """读全部节点；管理端列表复用同一套解析（坏 frontmatter 跳过）。"""
    return await _records(store, project)


def terms(query: str) -> list[str]:
    """查询词（含中文二元组）；管理端搜索与检索组共用。"""
    return _terms(query)


def score(record: NodeRecord, wanted: list[str]) -> float:
    """关键词打分；管理端列表只用 >0 判断命中，不展示具体分值。"""
    return _score(record, wanted)


@dataclass(frozen=True)
class NodeRecord:
    id: str
    node: NodeFrontmatter
    body: str


@dataclass(frozen=True)
class EdgeIndex:
    edges: list[dict[str, str]]
    unresolved: list[dict[str, str]]
    incident: dict[str, int]


async def _records(store: KnowledgeReader, project: str | None = None) -> list[NodeRecord]:
    records: list[NodeRecord] = []
    for node_id in await store.list_ids(project):
        try:
            node, body = await store.read(node_id)
        except (OSError, ValueError):
            # 手写坏的 frontmatter 不应该让整次检索失败；读单个节点时仍会报错。
            continue
        records.append(NodeRecord(node_id, node, body))
    return records


def _terms(query: str) -> list[str]:
    """查询词。中文没有空格分词，长词补二元组，避免只能整句精确命中。"""
    terms: list[str] = []
    for token in re.split(r"\s+", query.strip().lower()):
        if not token:
            continue
        terms.append(token)
        cjk = [char for char in token if "一" <= char <= "鿿"]
        if len(cjk) >= 4:
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
    return list(dict.fromkeys(terms))


def _snippet(body: str, terms: list[str]) -> str:
    flat = re.sub(r"\s+", " ", body).strip()
    lowered = flat.lower()
    position = -1
    for term in terms:
        position = lowered.find(term)
        if position >= 0:
            break
    if position < 0:
        return flat[:SNIPPET_CHARS]
    start = max(0, position - SNIPPET_CHARS // 3)
    piece = flat[start : start + SNIPPET_CHARS]
    prefix = "…" if start else ""
    suffix = "…" if start + SNIPPET_CHARS < len(flat) else ""
    return prefix + piece + suffix


def _score(record: NodeRecord, terms: list[str]) -> float:
    """旧子串打分；仅保留给 `kb_audit_list` 等未切换路径，`search` 已改用 BM25。"""
    title = record.node.title.lower()
    tags = [tag.lower() for tag in record.node.tags]
    body = record.body.lower()
    raw = 0.0
    for term in terms:
        if term in title:
            raw += 3
        if any(term in tag for tag in tags):
            raw += 2
        raw += min(body.count(term), 5)
    return raw


def _validate_kinds(kinds: list[str] | None) -> set[str] | None:
    if not kinds:
        return None
    valid = {kind.value for kind in Kind}
    unknown = [kind for kind in kinds if kind not in valid]
    if unknown:
        raise QueryError(f"kinds 里有未知取值 {unknown}；可选 {sorted(valid)}")
    return set(kinds)


async def search(
    store: KnowledgeReader,
    query: str,
    *,
    project: str | None = None,
    kinds: list[str] | None = None,
    tier: str = "canonical",
    limit: int = 8,
) -> dict[str, Any]:
    """关键词检索。`tier` 默认只给 canonical，显式 candidate/all 才看候选。"""
    if tier not in TIERS:
        raise QueryError(f"tier 必须是 {sorted(TIERS)} 之一，收到 {tier!r}")
    wanted_kinds = _validate_kinds(kinds)
    limit = max(1, min(limit, MAX_RESULTS))
    terms = _terms(query)
    if not terms:
        return {"results": [], "hint": "query 为空；请给出要查的概念、报错或项目"}

    scored: list[tuple[float, NodeRecord]] = []
    candidates: list[tuple[NodeRecord, list[str]]] = []
    for record in await _records(store, project):
        if wanted_kinds is not None and record.node.kind.value not in wanted_kinds:
            continue
        if tier != "all" and record.node.tier.value != tier:
            continue
        candidates.append((record, _document_tokens(record)))
    if candidates:
        index = BM25Okapi([tokens for _, tokens in candidates])
        raw_scores = index.get_scores(terms)
        ceiling = max(raw_scores, default=0.0)
        for (record, _), raw in zip(candidates, raw_scores, strict=True):
            if raw > 0:
                scored.append((raw, record))
    if not scored:
        return {
            "results": [],
            "hint": await _empty_hint(store, project, wanted_kinds, tier, terms),
        }

    scored.sort(key=lambda item: (-item[0], item[1].id))
    ceiling = scored[0][0]
    results = []
    for raw, record in scored[:limit]:
        results.append(
            {
                "id": record.id,
                "kind": record.node.kind.value,
                "tier": record.node.tier.value,
                "title": record.node.title,
                "score": normalize(raw, ceiling=ceiling),
                "matched": "bm25",
                "snippet": _snippet(record.body, terms),
                "updated_at": record.node.updated_at.isoformat(),
            }
        )
    return {"results": results}


def _document_tokens(record: NodeRecord) -> list[str]:
    """BM25 文档侧 token：标题、标签与正文，权重靠重复标题/标签体现。

    正文会切出一份词频，标题与标签各再计一次——比旧子串打分更平滑，且对
    「标题命中」的偏好保留。分词本身不改变召回面（与 `_terms` 同口径）。
    """
    tokens = tokenize(record.body)
    tokens.extend(tokenize(record.node.title))
    for tag in record.node.tags:
        tokens.extend(tokenize(tag))
    return tokens


async def _empty_hint(
    store: KnowledgeReader,
    project: str | None,
    kinds: set[str] | None,
    tier: str,
    terms: list[str],
) -> str:
    if tier == "all":
        return "没有匹配节点；换个关键词，或确认 project/kinds 过滤是否过窄"
    candidates = 0
    for record in await _records(store, project):
        if record.node.tier is not Tier.CANDIDATE:
            continue
        if kinds is not None and record.node.kind.value not in kinds:
            continue
        if _score(record, terms) > 0:
            candidates += 1
    if candidates:
        return f'没有 {tier} 命中；有 {candidates} 个候选节点匹配，传 tier="all" 可检索'
    return "没有匹配节点；换个关键词，或确认 project/kinds 过滤是否过窄"


def _check_id(node_id: str) -> None:
    if not node_id or node_id.startswith("/") or "\\" in node_id:
        raise NotFound(f"节点 id 不合法: {node_id!r}")
    if any(part in {"", ".", ".."} for part in node_id.split("/")):
        raise NotFound(f"节点 id 不合法: {node_id!r}")


async def edge_index(store: KnowledgeReader) -> EdgeIndex:
    """解析 `_edges.jsonl`。规则与图谱解析一致：完整 id 优先，其次唯一 slug。"""
    ids = set(await store.list_ids())
    slug_index: dict[str, list[str]] = {}
    for node_id in ids:
        slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

    def resolve(reference: str) -> str | None:
        if reference in ids:
            return reference
        candidates = slug_index.get(reference, []) if store.resolve_short_aliases else []
        return candidates[0] if len(candidates) == 1 else None

    edges: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    incident: dict[str, int] = {}
    async for line in store.edge_lines():
        if not line.strip():
            continue
        record = json.loads(line)
        source = resolve(str(record["source"]))
        target = resolve(str(record["target"]))
        if source is None or target is None:
            if not store.resolve_short_aliases:
                continue
            unresolved.append(
                {
                    "source": str(record["source"]),
                    "predicate": str(record["predicate"]),
                    "target": str(record["target"]),
                }
            )
            continue
        edges.append({"source": source, "predicate": str(record["predicate"]), "target": target})
        incident[source] = incident.get(source, 0) + 1
        incident[target] = incident.get(target, 0) + 1
    return EdgeIndex(edges=edges, unresolved=unresolved, incident=incident)


async def read_node(store: KnowledgeReader, node_id: str) -> dict[str, Any]:
    """真源全文 + frontmatter + 出/入边（各限 20 条）。"""
    _check_id(node_id)
    if not await store.exists(node_id):
        raise NotFound(f"节点不存在: {node_id}")
    node, body = await store.read(node_id)
    index = await edge_index(store)
    out = [
        {"predicate": edge["predicate"], "target": edge["target"]}
        for edge in index.edges
        if edge["source"] == node_id
    ][:EDGE_LIMIT]
    incoming = [
        {"predicate": edge["predicate"], "source": edge["source"]}
        for edge in index.edges
        if edge["target"] == node_id
    ][:EDGE_LIMIT]
    truncated = len(body) > READ_MAX_CHARS
    return {
        "id": node_id,
        "frontmatter": node.model_dump(mode="json", exclude_none=True),
        "body": body[:READ_MAX_CHARS],
        "truncated": truncated,
        "edges": {"out": out, "in": incoming},
        "source": node.model_dump(mode="json", exclude_none=True).get("source", []),
    }


def _validate_predicates(predicates: list[str] | None) -> set[str] | None:
    if not predicates:
        return None
    valid = {item.value for item in Predicate}
    unknown = [item for item in predicates if item not in valid]
    if unknown:
        raise QueryError(f"predicates 里有未知取值 {unknown}；可选 {sorted(valid)}")
    return set(predicates)


async def related(
    store: KnowledgeReader,
    node_id: str,
    *,
    depth: int = 1,
    predicates: list[str] | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """邻接子图；`depth` 上限 2，边两端都在结果里时才返回。"""
    _check_id(node_id)
    if not await store.exists(node_id):
        raise NotFound(f"节点不存在: {node_id}")
    depth = max(1, min(depth, 2))
    limit = max(1, min(limit, MAX_RESULTS))
    wanted = _validate_predicates(predicates)
    index = await edge_index(store)

    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in index.edges:
        if wanted is not None and edge["predicate"] not in wanted:
            continue
        adjacency.setdefault(edge["source"], []).append((edge["predicate"], edge["target"]))
        adjacency.setdefault(edge["target"], []).append((edge["predicate"], edge["source"]))

    distance = {node_id: 0}
    frontier = [node_id]
    for level in range(1, depth + 1):
        next_frontier: list[str] = []
        for current in frontier:
            for _, neighbour in adjacency.get(current, []):
                if neighbour not in distance:
                    distance[neighbour] = level
                    next_frontier.append(neighbour)
        frontier = next_frontier
        if len(distance) > limit:
            break

    selected = sorted(distance, key=lambda item: (distance[item], item))[:limit]
    chosen = set(selected)
    records = {record.id: record for record in await _records(store)}
    nodes = []
    for item in selected:
        record = records.get(item)
        if record is None:
            nodes.append({"id": item, "kind": None, "title": item, "tier": None})
            continue
        nodes.append(
            {
                "id": item,
                "kind": record.node.kind.value,
                "title": record.node.title,
                "tier": record.node.tier.value,
            }
        )
    edges = [
        edge
        for edge in index.edges
        if edge["source"] in chosen
        and edge["target"] in chosen
        and (wanted is None or edge["predicate"] in wanted)
    ]
    return {"id": node_id, "depth": depth, "nodes": nodes, "edges": edges}


async def audit_list(
    store: KnowledgeReader,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """只读治理问题清单：矛盾、断链、孤立、低置信、陈旧。

    问题是现算的（没有独立的问题库），`created_at` 是本次检出的时间。
    """
    limit = max(1, min(limit, MAX_RESULTS))
    offset = max(0, offset)
    records = await _records(store)
    index = await edge_index(store)
    now = datetime.now(UTC)
    issues: list[dict[str, Any]] = [
        {
            "type": "contradiction",
            "target": [edge["source"], edge["target"]],
            "created_at": now.isoformat(),
        }
        for edge in index.edges
        if edge["predicate"] == Predicate.CONTRADICTS.value
    ]
    issues.extend(
        {
            "type": "broken_link",
            "target": f"{edge['source']} -{edge['predicate']}-> {edge['target']}",
            "created_at": now.isoformat(),
        }
        for edge in index.unresolved
    )
    for record in records:
        references = index.incident.get(record.id, 0)
        if references == 0:
            issues.append({"type": "orphan", "target": record.id, "created_at": now.isoformat()})
        if record.node.confidence is not None and record.node.confidence < 0.5:
            issues.append(
                {
                    "type": "low_confidence",
                    "target": record.id,
                    "created_at": now.isoformat(),
                }
            )
        updated = record.node.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if references >= STALE_REFS and now - updated > timedelta(days=STALE_DAYS):
            issues.append({"type": "stale", "target": record.id, "created_at": now.isoformat()})

    issues.sort(key=lambda issue: (issue["type"], str(issue["target"])))
    return {
        "issues": issues[offset : offset + limit],
        "total": len(issues),
        "offset": offset,
        "limit": limit,
    }
