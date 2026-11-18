"""markdown 真源 → semantica ContextGraph 投影。

投影可随时丢弃重建；只读 markdown 与 `_edges.jsonl`，不反向写回真源。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from memhub.kb.store import KnowledgeStore

MAX_CONTENT = 4000


@dataclass
class ProjectionReport:
    nodes: int = 0
    edges: int = 0
    unresolved: list[str] = field(default_factory=list)


def build_graph(store: KnowledgeStore) -> tuple[object, ProjectionReport]:
    from semantica.context import ContextGraph  # type: ignore[import-untyped]

    graph = ContextGraph(advanced_analytics=False)
    report = ProjectionReport()
    ids: set[str] = set()
    slug_index: dict[str, list[str]] = {}

    for node_id in store.list_ids():
        node, body = store.read(node_id)
        added = graph.add_node(
            node_id,
            node.kind.value,
            content=body[:MAX_CONTENT],
            title=node.title,
            project=node.project,
            tier=node.tier.value,
            tags=node.tags,
            entity_kind=node.entity_kind.value if node.entity_kind else None,
        )
        if added:
            report.nodes += 1
        ids.add(node_id)
        slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

    def resolve(reference: str) -> str | None:
        if reference in ids:
            return reference
        candidates = slug_index.get(reference, [])
        return candidates[0] if len(candidates) == 1 else None

    for edges_path in sorted(store.root.rglob("_edges.jsonl")):
        for line in edges_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            source = resolve(str(record["source"]))
            target = resolve(str(record["target"]))
            if source is None or target is None:
                report.unresolved.append(
                    f"{record['source']} -{record['predicate']}-> {record['target']}"
                )
                continue
            if graph.add_edge(source, target, str(record["predicate"])):
                report.edges += 1

    return graph, report


def save_projection(store: KnowledgeStore, output: Path) -> ProjectionReport:
    graph, report = build_graph(store)
    output.parent.mkdir(parents=True, exist_ok=True)
    graph.save_to_file(output)  # type: ignore[attr-defined]
    return report
