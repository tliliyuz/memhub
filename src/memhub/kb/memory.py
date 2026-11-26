"""长期记忆条目、证据、门槛与注入选择的纯逻辑（规格 `long-term-memory-spec.md` §5/§7）。

不读写数据库：聚合任务把输入节点与现有条目状态传进来，这里只回答「哪些能成条、
哪些只能进候选、冲突如何标记」，以及「本次窗口注入哪几条」。存储职责在
`memhub.kb.pgstore`，LLM 调用在 `memhub.worker.memory`。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from memhub.kb.bm25 import BM25Okapi, tokenize

MEMORY_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"
MEMORY_SLUG_RE = re.compile(MEMORY_SLUG_PATTERN)
ENTRY_STATUSES = frozenset({"active", "deprecated"})
CANDIDATE_STATUSES = frozenset({"pending", "conflict", "promoted"})
CANDIDATE_REASONS = frozenset({"below_threshold", "conclusion_differs", "deprecated"})
DEFAULT_CONFIDENCE = 0.5


class MemoryAggregateError(RuntimeError):
    """聚合响应结构坏（不是 JSON、缺少 memories 数组）；整批失败而不是静默产出空结果。"""


def normalize_memory_slug(raw: str) -> str:
    """把模型给出的 slug 收敛到 kebab-case；无法收敛时返回空串。"""
    slug = raw.strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug if MEMORY_SLUG_RE.match(slug) else ""


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    node_id: str
    project: str
    session: str | None = None
    session_ref: str | None = None
    observed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "project": self.project,
            "session": self.session,
            "session_ref": self.session_ref,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    slug: str
    title: str
    conclusion: str
    boundary: str
    invalidation: str
    confidence: float
    evidence: tuple[str, ...]
    contradicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    slug: str
    title: str
    conclusion: str
    boundary: str
    invalidation: str
    confidence: float
    evidence: tuple[EvidenceRef, ...]
    contradicts: tuple[str, ...]
    session_count: int
    project_count: int
    action: Literal["create", "update"]


CandidateReason = Literal["below_threshold", "conclusion_differs", "deprecated"]


@dataclass(frozen=True, slots=True)
class CandidateWrite:
    slug: str
    title: str
    conclusion: str
    boundary: str
    invalidation: str
    confidence: float
    evidence: tuple[EvidenceRef, ...]
    contradicts: tuple[str, ...]
    session_count: int
    project_count: int
    status: Literal["pending", "conflict", "promoted"]
    reason: CandidateReason


@dataclass(slots=True)
class MemoryPlan:
    writes: list[MemoryWrite] = field(default_factory=list)
    candidates: list[CandidateWrite] = field(default_factory=list)


def _content_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0] in {"```json", "```"} and lines[-1] == "```":
            return "\n".join(lines[1:-1])
    return text


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_CONFIDENCE
    number = float(value)
    if not math.isfinite(number):
        return DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, number))


def parse_memories(raw: str, nodes: Mapping[str, Mapping[str, Any]]) -> list[MemoryDraft]:
    """解析聚合响应；逐条丢弃非法项，结构坏则抛 `MemoryAggregateError`。"""
    try:
        data = json.loads(_strip_fence(raw))
    except (ValueError, RecursionError):
        raise MemoryAggregateError("聚合响应不是有效 JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("memories"), list):
        raise MemoryAggregateError("聚合响应必须显式提供 memories 数组")

    drafts: list[MemoryDraft] = []
    for item in data["memories"]:
        if not isinstance(item, dict):
            continue
        slug = normalize_memory_slug(str(item.get("slug") or ""))
        title = str(item.get("title") or "").strip()
        conclusion = str(item.get("conclusion") or "").strip()
        if not slug or not title or not conclusion:
            continue
        raw_evidence = item.get("evidence")
        if not isinstance(raw_evidence, list):
            continue
        evidence = tuple(
            dict.fromkeys(ref for ref in raw_evidence if isinstance(ref, str) and ref in nodes)
        )
        if not evidence:
            continue
        raw_contradicts = item.get("contradicts")
        contradicts = (
            tuple(
                dict.fromkeys(
                    candidate
                    for ref in raw_contradicts
                    if isinstance(ref, str)
                    if (candidate := normalize_memory_slug(ref)) and candidate != slug
                )
            )
            if isinstance(raw_contradicts, list)
            else ()
        )
        drafts.append(
            MemoryDraft(
                slug=slug,
                title=title,
                conclusion=conclusion,
                boundary=str(item.get("boundary") or "").strip(),
                invalidation=str(item.get("invalidation") or "").strip(),
                confidence=_confidence(item.get("confidence")),
                evidence=evidence,
                contradicts=contradicts,
            )
        )
    return drafts


def _observed_at(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def evidence_refs(
    node_ids: Sequence[str], nodes: Mapping[str, Mapping[str, Any]]
) -> tuple[EvidenceRef, ...]:
    """把节点 id 展开成证据引用；每个 session 来源一条，跨会话计数靠 `session` 去重。"""
    refs: list[EvidenceRef] = []
    for node_id in node_ids:
        node = nodes.get(node_id)
        if node is None:
            continue
        project = str(node.get("project") or "")
        sources = node.get("source")
        sessions: list[str] = []
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, Mapping):
                    continue
                if source.get("type") != "session":
                    continue
                ref = source.get("ref")
                if isinstance(ref, str) and ref and ref not in sessions:
                    sessions.append(ref)
        observed_at = _observed_at(node.get("updated_at"))
        if not sessions:
            refs.append(
                EvidenceRef(
                    node_id=node_id,
                    project=project,
                    observed_at=observed_at,
                )
            )
            continue
        refs.extend(
            EvidenceRef(
                node_id=node_id,
                project=project,
                session=f"{project}:{ref}",
                session_ref=ref,
                observed_at=observed_at,
            )
            for ref in sessions
        )
    return tuple(refs)


def count_evidence(evidence: Sequence[EvidenceRef]) -> tuple[int, int]:
    """(独立会话数, 项目数)；没有 session 来源的节点不计入会话数。"""
    sessions = {item.session for item in evidence if item.session}
    projects = {item.project for item in evidence if item.project}
    return len(sessions), len(projects)


def _existing_evidence(value: object) -> tuple[EvidenceRef, ...]:
    if not isinstance(value, list):
        return ()
    refs: list[EvidenceRef] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        node_id = item.get("node_id")
        project = item.get("project")
        if not isinstance(node_id, str) or not isinstance(project, str):
            continue
        refs.append(
            EvidenceRef(
                node_id=node_id,
                project=project,
                session=item.get("session") if isinstance(item.get("session"), str) else None,
                session_ref=(
                    item.get("session_ref") if isinstance(item.get("session_ref"), str) else None
                ),
                observed_at=(
                    item.get("observed_at") if isinstance(item.get("observed_at"), str) else None
                ),
            )
        )
    return tuple(refs)


def _merge_evidence(
    existing: Sequence[EvidenceRef], incoming: Sequence[EvidenceRef]
) -> tuple[EvidenceRef, ...]:
    merged: list[EvidenceRef] = []
    seen: set[tuple[str, str | None]] = set()
    for item in (*existing, *incoming):
        key = (item.node_id, item.session)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return tuple(merged)


def plan_memories(
    drafts: Sequence[MemoryDraft],
    nodes: Mapping[str, Mapping[str, Any]],
    existing: Mapping[str, Mapping[str, Any]],
    *,
    min_sessions: int,
    min_projects: int,
) -> MemoryPlan:
    """按门槛与现有条目状态裁决：写条目、写候选或什么都不做。"""
    plan = MemoryPlan()
    for draft in drafts:
        evidence = evidence_refs(draft.evidence, nodes)
        session_count, project_count = count_evidence(evidence)
        current = existing.get(draft.slug)
        current_status = str(current.get("status")) if current else None

        if current_status == "deprecated":
            plan.candidates.append(
                _candidate(draft, evidence, session_count, project_count, "conflict", "deprecated")
            )
            continue
        if current_status == "active":
            assert current is not None
            if _content_key(str(current.get("conclusion") or "")) == _content_key(draft.conclusion):
                merged = _merge_evidence(_existing_evidence(current.get("evidence")), evidence)
                merged_sessions, merged_projects = count_evidence(merged)
                plan.writes.append(
                    _write(
                        draft,
                        merged,
                        merged_sessions,
                        merged_projects,
                        "update",
                    )
                )
            else:
                plan.candidates.append(
                    _candidate(
                        draft,
                        evidence,
                        session_count,
                        project_count,
                        "conflict",
                        "conclusion_differs",
                    )
                )
            continue

        if session_count >= min_sessions and project_count >= min_projects:
            plan.writes.append(_write(draft, evidence, session_count, project_count, "create"))
        else:
            plan.candidates.append(
                _candidate(
                    draft,
                    evidence,
                    session_count,
                    project_count,
                    "pending",
                    "below_threshold",
                )
            )
    return plan


def _write(
    draft: MemoryDraft,
    evidence: tuple[EvidenceRef, ...],
    session_count: int,
    project_count: int,
    action: Literal["create", "update"],
) -> MemoryWrite:
    return MemoryWrite(
        slug=draft.slug,
        title=draft.title,
        conclusion=draft.conclusion,
        boundary=draft.boundary,
        invalidation=draft.invalidation,
        confidence=draft.confidence,
        evidence=evidence,
        contradicts=draft.contradicts,
        session_count=session_count,
        project_count=project_count,
        action=action,
    )


def _candidate(
    draft: MemoryDraft,
    evidence: tuple[EvidenceRef, ...],
    session_count: int,
    project_count: int,
    status: Literal["pending", "conflict", "promoted"],
    reason: Literal["below_threshold", "conclusion_differs", "deprecated"],
) -> CandidateWrite:
    contradicts = draft.contradicts
    if reason in {"conclusion_differs", "deprecated"}:
        contradicts = tuple(dict.fromkeys((*contradicts, draft.slug)))
    return CandidateWrite(
        slug=draft.slug,
        title=draft.title,
        conclusion=draft.conclusion,
        boundary=draft.boundary,
        invalidation=draft.invalidation,
        confidence=draft.confidence,
        evidence=evidence,
        contradicts=contradicts,
        session_count=session_count,
        project_count=project_count,
        status=status,
        reason=reason,
    )


def _entry_text(entry: Mapping[str, Any]) -> str:
    lines = [f"- [{entry.get('slug', '')}] {entry.get('conclusion', '')}"]
    if entry.get("boundary"):
        lines.append(f"  边界：{entry['boundary']}")
    if entry.get("invalidation"):
        lines.append(f"  失效条件：{entry['invalidation']}")
    return "\n".join(lines)


def select_memories(
    entries: Sequence[Mapping[str, Any]],
    query: str,
    *,
    top_k: int = 8,
    budget_chars: int = 4000,
) -> list[dict[str, Any]]:
    """按 BM25 相关性选 top-k；只取分数 > 0 的条目，并受字符预算约束。"""
    if top_k <= 0 or budget_chars <= 0 or not query.strip() or not entries:
        return []
    corpus = [
        tokenize(
            f"{entry.get('title', '')}\n{entry.get('conclusion', '')}\n{entry.get('boundary', '')}"
        )
        for entry in entries
    ]
    terms = tokenize(query, dedupe=True)
    if not terms:
        return []
    scores = BM25Okapi(corpus).get_scores(terms)
    ranked = sorted(
        ((score, index) for index, score in enumerate(scores) if score > 0),
        key=lambda item: (-item[0], item[1]),
    )
    selected: list[dict[str, Any]] = []
    used = 0
    for _score, index in ranked[:top_k]:
        entry = dict(entries[index])
        used += len(_entry_text(entry))
        if used > budget_chars:
            break
        selected.append(entry)
    return selected


def render_memory_block(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "（本次未注入长期记忆）"
    body = "\n".join(_entry_text(entry) for entry in entries)
    return f"长期记忆（判断与归一化准则；不是事实来源，不得写入 evidence）：\n{body}"
