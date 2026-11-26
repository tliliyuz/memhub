"""把抽取结果合并进知识真源（PG `kb_*`；文件存储仅测试夹具与迁移工具使用）。

规则（ADR-0014：写入即 canonical，取消候选门槛）：
- 新节点一律 `tier=canonical`，默认检索可见。
- 已有节点（任意层级）继续追加式合并：追加新增段落与来源，不覆盖标题；同一正文不重复追加。
- 永不删除。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.worker.schema import ExtractedNode, Extraction


@dataclass
class MergeReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    edges_added: int = 0

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated)


async def merge(
    store: KnowledgeStore | PgKnowledgeStore,
    extraction: Extraction,
    *,
    project: str,
    source: SourceRef,
    now: datetime | None = None,
    lock_timeout: float = 10.0,
    check_target: Callable[[], Awaitable[None]] | None = None,
) -> MergeReport:
    moment = now or datetime.now(UTC)
    report = MergeReport()
    slug_to_id: dict[str, str] = {}

    # 一次写入 = 一个写作用域：文件版是跨进程锁，PG 版是一个事务。
    async with store.write_scope(timeout=lock_timeout):
        if check_target is None:
            await store.guard_write(project)
        else:
            await check_target()
        for node in extraction.nodes:
            node_id = f"{project}/{node.kind.value}/{node.slug}"
            slug_to_id[node.slug] = node_id
            if not await store.exists(node_id):
                await store.write(
                    node_id, _new_node(node_id, node, project, source, moment), node.body
                )
                report.created.append(node_id)
                continue

            existing, existing_body = await store.read(node_id)
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
    node_id: str, node: ExtractedNode, project: str, source: SourceRef, now: datetime
) -> NodeFrontmatter:
    return NodeFrontmatter(
        id=node_id,  # PG 版要求与写入 id 一致；文件版同样接受
        kind=node.kind,
        entity_kind=node.entity_kind,
        title=node.title,
        tier=Tier.CANONICAL,
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
