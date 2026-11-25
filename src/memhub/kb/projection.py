"""真源 → semantica ContextGraph 投影（异步 IO）。

投影可随时丢弃重建；只读真源的节点与边（PG 表或迁移期的 markdown），不反向写回。
semantica 只有同步 API，`save_to_file` 用 `anyio.to_thread` 放到线程里执行；
核心数据读取与组装仍是异步实现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
from anyio import Path as AsyncPath

from memhub.kb import archive, manage
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore

MAX_CONTENT = 4000


@dataclass
class ProjectionReport:
    nodes: int = 0
    edges: int = 0
    unresolved: list[str] = field(default_factory=list)


async def build_graph(
    store: KnowledgeStore | PgKnowledgeStore,
) -> tuple[Any, ProjectionReport]:
    from semantica.context import ContextGraph  # type: ignore[import-untyped]

    graph = ContextGraph(advanced_analytics=False)
    report = ProjectionReport()
    ids: set[str] = set()
    slug_index: dict[str, list[str]] = {}

    for node_id in await store.list_ids():
        node, body = await store.read(node_id)
        # semantica 把 `content` 当节点标签渲染（画布/搜索建议都用它），
        # 所以这里放短标题；正文作为属性保留，仍参与搜索与检查器展示。
        added = graph.add_node(
            node_id,
            node.kind.value,
            content=node.title,
            body=body[:MAX_CONTENT],
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

    async for line in store.edge_lines():
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


async def save_projection(
    store: KnowledgeStore | PgKnowledgeStore,
    output: Path,
    *,
    clear_archive_dirty: bool = False,
) -> ProjectionReport:
    # 文件真源：与写者互斥，且有未完成归档时不发布新投影。
    # PG 真源：写入是事务，投影只是缓存，读取期间无需再拿跨进程文件锁。
    if isinstance(store, PgKnowledgeStore):
        graph, report = await build_graph(store)
        await AsyncPath(output.parent).mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(graph.save_to_file, output)
        return report

    async with manage.write_lock(store.root):
        graph, report = await build_graph(store)
        await AsyncPath(output.parent).mkdir(parents=True, exist_ok=True)
        # semantica 的保存接口是同步的，且没有异步替代品。
        await anyio.to_thread.run_sync(graph.save_to_file, output)
        if clear_archive_dirty:
            await archive.clear_projection_dirty(store.root)
        return report
