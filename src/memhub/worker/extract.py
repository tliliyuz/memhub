"""单文档抽取：分节 → LLM → 校验 → 合并同一文档内的结果。

容错边界：**结构坏**（不是 JSON、形状不对）算失败；**个别条目坏**（未知谓词、
非法 slug、缺 entity_kind）只丢那一条并告警。一枚谓词漂移就让整篇文档留在队列
里无限重试、每轮重新付费，比丢一条边糟得多。
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from memhub.contract import Kind, Predicate
from memhub.worker.llm import DEFAULT_MAX_TOKENS, LLMClient, parse_json
from memhub.worker.prompts import render
from memhub.worker.render import SessionBlock, SessionWindow, session_windows
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


SESSION_KINDS = {Kind.FACT, Kind.DECISION, Kind.PROCEDURE, Kind.PITFALL}
# 只拒绝可明确识别的形式，不以标题、字符数或配额替代内容判断。
_NOISE = re.compile(
    r"(?:hi|hello|thanks(?: a lot)?|thank you|ok(?:ay)?|got it|done|"
    r"(?:still |currently )?running|(?:i |we )?just (?:finished|committed|pushed)|"
    r"follow (?:the )?best practices|use best practices|keep it simple|"
    r"你好|谢谢|收到|好的|明白了?|正在运行|刚提交(?:了)?|已完成|遵循最佳实践)[.!。！]*",
    re.IGNORECASE,
)
_TENTATIVE = re.compile(
    r"^(?:(?:i|we) (?:suspect|guess|think)\b|(?:maybe|perhaps|probably|hypothesis)\b|"
    r"(?:unconfirmed|not (?:yet )?verified)\b|"
    r"(?:我(?:猜|怀疑)|可能|也许|大概|猜测|推测|假设|尚未验证|未经验证|待验证))",
    re.IGNORECASE,
)
_PROGRESS = re.compile(
    r"^(?:(?:i(?:'m| am)|we(?:'re| are)) (?:currently |still )?(?:running|working on|waiting for)\b|"
    r"(?:i|we) just (?:finished|committed|pushed)\b|"
    r"(?:我?正在(?:运行|执行|检查|处理|等待)|我?刚(?:刚)?(?:提交|推送)|当前进度[：:]))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Citation:
    block: str
    quote: str


@dataclass(frozen=True, slots=True)
class _SessionNode:
    node: ExtractedNode
    evidence: tuple[_Citation, ...]


def _content_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _noise(text: str) -> bool:
    # 识别单纯的进度、寒暄、通用建议与未验证推测。多句内容仍需提示词判断含义。
    text = _content_key(text)
    if not any(char.isalnum() for char in text):
        return True
    return bool(_NOISE.fullmatch(text) or _TENTATIVE.match(text) or _PROGRESS.match(text))


async def extract_session(
    client: LLMClient,
    *,
    template: str,
    path: str,
    blocks: Sequence[SessionBlock],
    model: str,
    max_chars: int = 12000,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Extraction:
    """抽取有逐字出处的会话候选；畸形窗失败时不返回任何部分结果。"""
    nodes: list[_SessionNode] = []
    edges: list[ExtractedEdge] = []
    for index, window in enumerate(session_windows(blocks, max_chars), 1):
        chunk_path = f"{path}#chunk{index}"
        prompt = render(template, path=chunk_path, text=window.text)
        raw = await client.complete(prompt, model=model, max_tokens=max_tokens)
        _validate_session(raw, window, chunk_path, nodes, edges)
    return _dedupe_session(nodes, edges)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("JSON 字段重复")
    return data


def _reject_non_json_number(_value: str) -> None:
    raise ValueError("JSON 不允许非有限数字")


def _session_payload(raw: str, path: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0] in {"```json", "```"} and lines[-1] == "```":
            text = "\n".join(lines[1:-1])
    try:
        data = json.loads(
            text, object_pairs_hook=_unique_fields, parse_constant=_reject_non_json_number
        )
    except (ValueError, RecursionError):
        raise ExtractionFailed(f"{path}: 会话响应不是有效 JSON") from None
    if not isinstance(data, dict) or set(data) != {"nodes", "edges"}:
        raise ExtractionFailed(f"{path}: 会话响应必须显式提供 nodes 和 edges")
    return data


def _session_items(value: object, path: str, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ExtractionFailed(f"{path}: {name} 必须是对象数组")
    return [dict(item) for item in value]


def _session_evidence(
    item: dict[str, object], window: SessionWindow, path: str
) -> tuple[_Citation, ...]:
    if "evidence" not in item:
        return ()
    citations = _session_items(item.pop("evidence"), path, "evidence")
    visible = {block.id: block for block in window.blocks}
    fresh = set(visible)
    if window.context is not None:
        visible[window.context.id] = window.context
    evidence: list[_Citation] = []
    rejected = False
    for citation in citations:
        block_id = citation.get("block")
        quote = citation.get("quote")
        if (
            set(citation) != {"block", "quote"}
            or not isinstance(block_id, str)
            or not isinstance(quote, str)
        ):
            raise ExtractionFailed(f"{path}: 引用必须提供字符串 block 和 quote")
        block = visible.get(block_id)
        if block is None or _noise(quote) or quote not in block.text:
            rejected = True
            continue
        # 不允许只截取同一行的猜测结论、藏起其前置限定词。
        offset = block.text.index(quote)
        line_start = block.text.rfind("\n", 0, offset) + 1
        line_end = block.text.find("\n", offset + len(quote))
        line = block.text[line_start:] if line_end < 0 else block.text[line_start:line_end]
        if _noise(line):
            rejected = True
            continue
        evidence.append(_Citation(block_id, quote))
    if rejected or not any(citation.block in fresh for citation in evidence):
        return ()
    return tuple(evidence)


def _validate_session(
    raw: str,
    window: SessionWindow,
    path: str,
    nodes: list[_SessionNode],
    edges: list[ExtractedEdge],
) -> None:
    payload = _session_payload(raw, path)
    raw_nodes = _session_items(payload["nodes"], path, "nodes")
    raw_edges = _session_items(payload["edges"], path, "edges")
    for item in raw_nodes:
        evidence = _session_evidence(item, window, path)
        _require_session_strings(item, path, ("slug", "kind", "title", "body"))
        item["slug"] = normalize_slug(str(item["slug"]))
        if item["kind"] not in SESSION_KINDS or not item["slug"]:
            continue
        try:
            node = ExtractedNode.model_validate(item)
        except ValueError:
            raise ExtractionFailed(f"{path}: 会话节点结构无效") from None
        # 不把已有节点 schema 扩展为证据存储；只在本次门禁内使用引用。
        if evidence and node.entity_kind is None and not _noise(node.body):
            nodes.append(_SessionNode(node, evidence))
    for item in raw_edges:
        evidence = _session_evidence(item, window, path)
        _require_session_strings(item, path, ("source", "target", "predicate"))
        # 不猜测关系，不把完整路径或其他外部引用改写成本窗 slug。
        if item["predicate"] not in PREDICATE_VALUES:
            continue
        try:
            edge = ExtractedEdge.model_validate(item)
        except ValueError:
            raise ExtractionFailed(f"{path}: 会话边结构无效") from None
        if evidence:
            edges.append(edge)


def _require_session_strings(item: dict[str, object], path: str, fields: tuple[str, ...]) -> None:
    if any(not isinstance(item.get(field), str) for field in fields):
        raise ExtractionFailed(f"{path}: 会话条目缺失必要字符串字段")


def _claim_key(text: str) -> str:
    # 仅消除呈现差异，保留正文内部标点、数值、措辞及其顺序。
    return _content_key(text).rstrip(".。")


def _dedupe_session(nodes: list[_SessionNode], edges: list[ExtractedEdge]) -> Extraction:
    retained: list[ExtractedNode] = []
    by_identity: dict[tuple[Kind, str], int] = {}
    by_content: dict[tuple[Kind, str], int] = {}
    by_supported_claim: dict[tuple[Kind, str, str], int] = {}
    aliases: dict[str, set[int]] = defaultdict(set)
    ambiguous_slugs: set[str] = set()
    for candidate in nodes:
        node = candidate.node
        identity = (node.kind, node.slug)
        body = _content_key(node.body)
        title = _claim_key(node.title)
        quotes = {_claim_key(citation.quote) for citation in candidate.evidence}
        # 不因共享引用而合并。只有相同的规范化正文，或标题、正文和引用共同
        # 指向同一简短陈述时，证据才可作为跨 slug 的重复键。
        claim = (node.kind, title, _claim_key(node.body))
        supported = title in quotes and title == claim[2]
        known_identity = by_identity.get(identity)
        known_content = by_content.get((node.kind, body))
        known_claim = by_supported_claim.get(claim) if supported else None
        if known_identity is not None:
            index = known_identity
            if known_content != index and known_claim != index:
                ambiguous_slugs.add(node.slug)
                # 同一身份只能保留一份正文；不要将被舍弃的正文登记为其别名，
                # 否则这个内容后来使用不同合法 slug 时也会消失。
                continue
        elif known_content is not None:
            index = known_content
        elif known_claim is not None:
            index = known_claim
        else:
            index = len(retained)
            retained.append(node)
        by_identity[identity] = index
        by_content.setdefault((node.kind, body), index)
        if supported:
            by_supported_claim.setdefault(claim, index)
        aliases[node.slug].add(index)

    seen: dict[tuple[str, Predicate, str], ExtractedEdge] = {}
    for edge in edges:
        source = aliases.get(edge.source, set())
        target = aliases.get(edge.target, set())
        if (
            len(source) != 1
            or len(target) != 1
            or edge.source in ambiguous_slugs
            or edge.target in ambiguous_slugs
        ):
            continue
        origin, dest = retained[next(iter(source))], retained[next(iter(target))]
        if (
            origin.slug == dest.slug
            or len(aliases[origin.slug]) != 1
            or len(aliases[dest.slug]) != 1
        ):
            continue
        if origin.slug in ambiguous_slugs or dest.slug in ambiguous_slugs:
            continue
        key = (origin.slug, edge.predicate, dest.slug)
        seen.setdefault(key, edge.model_copy(update={"source": origin.slug, "target": dest.slug}))
    return Extraction(nodes=retained, edges=list(seen.values()))


async def extract_document(
    client: LLMClient,
    *,
    template: str,
    path: str,
    text: str,
    model: str,
    max_chars: int = 12000,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Extraction:
    chunks = split_markdown(text, max_chars=max_chars)
    if not chunks:
        return Extraction()

    collected: list[Extraction] = []
    for index, chunk in enumerate(chunks):
        chunk_path = path if len(chunks) == 1 else f"{path}#chunk{index + 1}"
        prompt = render(template, path=chunk_path, text=chunk)
        raw = await client.complete(prompt, model=model, max_tokens=max_tokens)
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
