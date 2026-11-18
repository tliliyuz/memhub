"""单文档抽取：分节 → LLM → 校验 → 合并同一文档内的结果。"""

from __future__ import annotations

from memhub.worker.llm import LLMClient, parse_json
from memhub.worker.prompts import render
from memhub.worker.schema import Extraction, normalize_slug
from memhub.worker.split import split_markdown


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
        payload = _normalize_payload(data)
        try:
            collected.append(Extraction.model_validate(payload))
        except ValueError as exc:
            raise ExtractionFailed(f"{chunk_path}: {exc}") from exc

    merged = Extraction(
        nodes=[node for item in collected for node in item.nodes],
        edges=[edge for item in collected for edge in item.edges],
    )
    return merged.dedupe()


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
        edges.append({"source": source, "predicate": edge.get("predicate"), "target": target})

    return {"nodes": nodes, "edges": edges}


def _as_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
