"""单文档抽取：分节 → LLM → 校验 → 合并同一文档内的结果。

容错边界：**结构坏**（不是 JSON、形状不对）算失败；**个别条目坏**（未知谓词、
非法 slug、缺 entity_kind）只丢那一条并告警。一枚谓词漂移就让整篇文档留在队列
里无限重试、每轮重新付费，比丢一条边糟得多。
"""

from __future__ import annotations

import sys

from memhub.contract import Predicate
from memhub.worker.llm import LLMClient, parse_json
from memhub.worker.prompts import render
from memhub.worker.schema import (
    ExtractedEdge,
    ExtractedNode,
    Extraction,
    normalize_slug,
)
from memhub.worker.split import split_markdown

PREDICATE_VALUES = {item.value for item in Predicate}
FALLBACK_PREDICATE = Predicate.RELATED_TO.value


class ExtractionFailed(RuntimeError):
    pass


def extract_document(
    client: LLMClient,
    *,
    template: str,
    path: str,
    text: str,
    model: str,
    max_chars: int = 12000,
    max_tokens: int = 8000,
) -> Extraction:
    chunks = split_markdown(text, max_chars=max_chars)
    if not chunks:
        return Extraction()

    collected: list[Extraction] = []
    for index, chunk in enumerate(chunks):
        chunk_path = path if len(chunks) == 1 else f"{path}#chunk{index + 1}"
        prompt = render(template, path=chunk_path, text=chunk)
        raw = client.complete(prompt, model=model, max_tokens=max_tokens)
        data = parse_json(raw)
        collected.append(_validate(_normalize_payload(data), chunk_path))

    merged = Extraction(
        nodes=[node for item in collected for node in item.nodes],
        edges=[edge for item in collected for edge in item.edges],
    )
    return merged.dedupe()


def _validate(payload: dict[str, object], chunk_path: str) -> Extraction:
    """逐条校验：坏条目丢弃并计数，一条都不会拖垮整篇。

    唯一仍然失败的情形是「模型给了条目但一条都不合法」——那说明契约跑偏
    （提示词或模型版本变了），静默产出空结果会掩盖问题。
    """
    raw_nodes = _as_list(payload.get("nodes"))
    nodes: list[ExtractedNode] = []
    dropped_nodes = 0
    for raw_node in raw_nodes:
        try:
            nodes.append(ExtractedNode.model_validate(raw_node))
        except ValueError:
            dropped_nodes += 1

    valid_slugs = {node.slug for node in nodes}
    raw_edges = _as_list(payload.get("edges"))
    edges: list[ExtractedEdge] = []
    dropped_edges = 0
    for raw_edge in raw_edges:
        if str(raw_edge.get("source", "")) not in valid_slugs:
            dropped_edges += 1
            continue
        try:
            edges.append(ExtractedEdge.model_validate(raw_edge))
        except ValueError:
            dropped_edges += 1

    if raw_nodes and not nodes:
        raise ExtractionFailed(f"{chunk_path}: {len(raw_nodes)} 个节点全部校验失败")
    if dropped_nodes or dropped_edges:
        print(
            f"[extract] {chunk_path}: 丢弃 {dropped_nodes} 个节点 / {dropped_edges} 条边",
            file=sys.stderr,
        )
    return Extraction(nodes=nodes, edges=edges)


def _normalize_payload(data: dict[str, object]) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    for raw_node in _as_list(data.get("nodes")):
        node = dict(raw_node)
        node["slug"] = normalize_slug(str(node.get("slug", "")))
        if not node["slug"]:
            continue
        nodes.append(node)

    valid_slugs = {str(node["slug"]) for node in nodes}
    edges: list[dict[str, object]] = []
    for raw_edge in _as_list(data.get("edges")):
        edge = dict(raw_edge)
        source = normalize_slug(str(edge.get("source", "")))
        target = normalize_slug(str(edge.get("target", "")))
        # 跨文档目标允许保留；源端必须在本文档内，否则关系无法溯源。
        if source not in valid_slugs or not target:
            continue
        # 谓词是闭集，模型偶尔会自造（实测 alternative_to）。收敛到 related_to：
        # 关系本身是真的，只是用词越界，没必要因此丢边或整篇失败。
        predicate = str(edge.get("predicate", FALLBACK_PREDICATE))
        if predicate not in PREDICATE_VALUES:
            predicate = FALLBACK_PREDICATE
        edges.append({"source": source, "predicate": predicate, "target": target})

    return {"nodes": nodes, "edges": edges}


def _as_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
