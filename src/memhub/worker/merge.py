"""把抽取结果合并进 markdown 真源。

规则：
- 自动写入一律 `tier=candidate`。
- 目标已存在且为 `canonical` 时**不修改**，记入 `skipped`（由治理流程处理）。
- 同一 slug 重复抽取只追加新增段落，不覆盖原文；来源去重。
- 永不删除。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from memhub.contract import (
    Edge,
    Kind,
    NodeFrontmatter,
    QuestionStatus,
    SourceRef,
    Tier,
)
from memhub.kb.manage import guard_project_write, write_lock
from memhub.kb.store import KnowledgeStore
from memhub.worker.schema import ExtractedNode, Extraction


@dataclass
class MergeReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped_canonical: list[str] = field(default_factory=list)
    edges_added: int = 0

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated)


async def merge(
    store: KnowledgeStore,
    extraction: Extraction,
    *,
    project: str,
    source: SourceRef,
    now: datetime | None = None,
    lock_timeout: float = 10.0,
) -> MergeReport:
    moment = now or datetime.now(UTC)
    report = MergeReport()
    slug_to_id: dict[str, str] = {}

    async with write_lock(store.root, timeout=lock_timeout):
        await guard_project_write(store.root, project)
        for node in extraction.nodes:
            node_id = f"{project}/{node.kind.value}/{node.slug}"
            slug_to_id[node.slug] = node_id
            if not await store.exists(node_id):
                await store.write(node_id, _new_node(node, project, source, moment), node.body)
                report.created.append(node_id)
                continue

            existing, existing_body = await store.read(node_id)
            if existing.tier is Tier.CANONICAL:
                report.skipped_canonical.append(node_id)
                continue

            updated = _merge_existing(existing, node, source, moment)
            body = _merge_body(existing_body, node.body, moment)
            await store.write(node_id, updated, body)
            report.updated.append(node_id)

        edges = [
            Edge(
                source=slug_to_id.get(edge.source, edge.source),
                predicate=edge.predicate,
                target=slug_to_id.get(edge.target, edge.target),
                source_doc=source.ref,
            )
            for edge in extraction.edges
        ]
        report.edges_added = await store.append_edges(project, edges, source.ref)
    return report


def _new_node(
    node: ExtractedNode, project: str, source: SourceRef, now: datetime
) -> NodeFrontmatter:
    return NodeFrontmatter(
        id="",  # 由 store 覆盖
        kind=node.kind,
        entity_kind=node.entity_kind,
        title=node.title,
        tier=Tier.CANDIDATE,
        confidence=node.confidence,
        project=project,
        tags=node.tags,
        source=[source],
        created_at=now,
        updated_at=now,
        status=QuestionStatus.OPEN if node.kind is Kind.QUESTION else None,
    )


def _merge_existing(
    existing: NodeFrontmatter,
    node: ExtractedNode,
    source: SourceRef,
    now: datetime,
) -> NodeFrontmatter:
    sources = list(existing.source)
    if not any(item.type == source.type and item.ref == source.ref for item in sources):
        sources.append(source)
    confidence = existing.confidence
    if node.confidence is not None:
        confidence = max(confidence or 0.0, node.confidence)
    tags = sorted(set(existing.tags) | set(node.tags))
    return existing.model_copy(
        update={
            "updated_at": now,
            "confidence": confidence,
            "tags": tags,
            "source": sources,
        }
    )


def _merge_body(existing_body: str, new_body: str, now: datetime) -> str:
    incoming = new_body.strip()
    if not incoming or incoming in existing_body:
        return existing_body
    stamp = now.date().isoformat()
    return f"{existing_body.rstrip()}\n\n## 补充（{stamp}）\n\n{incoming}\n"
