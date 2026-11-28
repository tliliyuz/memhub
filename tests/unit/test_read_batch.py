"""批量读回归：读接口不得对每个节点逐个开读（PG 迁移后 N+1）。

4441 个节点时，`list_nodes` / `stats` / `audit_list` 若对每条记录单独
`store.read()`（PG 每次新开 session），接口会从 ~100ms 退化到十几秒。
这里用计数版读取面锁住「整表一次读 + 可选正文投影」的调用形状。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from memhub.contract import Kind, NodeFrontmatter, Tier
from memhub.kb import manage, query

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
NODES = 4441
REVISION = "rev0123456789abc"
BODY = "正文"


def _node(node_id: str) -> NodeFrontmatter:
    return NodeFrontmatter(
        id=node_id,
        kind=Kind.FACT,
        title=f"节点 {node_id}",
        tier=Tier.CANONICAL,
        project=node_id.split("/", 1)[0],
        created_at=NOW,
        updated_at=NOW,
    )


class CountingReader:
    """只实现读取面的计数替身；`read` 与 `read_many` 分开计数。"""

    resolve_short_aliases = True

    def __init__(self) -> None:
        self.ids = [f"memhub/fact/n{index}" for index in range(NODES)]
        self.read_calls = 0
        self.read_many_calls = 0
        self.list_ids_calls = 0
        self.edge_calls = 0

    async def list_ids(self, project: str | None = None) -> list[str]:
        self.list_ids_calls += 1
        return list(self.ids)

    async def exists(self, node_id: str) -> bool:
        return node_id in set(self.ids)

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        self.read_calls += 1
        return _node(node_id), BODY

    async def read_many(
        self, node_ids: list[str], *, include_body: bool = True
    ) -> list[query.NodeRecord]:
        self.read_many_calls += 1
        return [
            query.NodeRecord(
                node_id,
                _node(node_id),
                BODY if include_body else "",
                REVISION,
                len(BODY),
            )
            for node_id in node_ids
        ]

    async def edge_lines(self) -> AsyncIterator[str]:
        self.edge_calls += 1
        return
        yield  # pragma: no cover - 只为把函数标记成异步生成器

    @property
    def total_calls(self) -> int:
        return self.read_calls + self.read_many_calls + self.list_ids_calls + self.edge_calls


async def test_list_nodes_reads_once_instead_of_per_node() -> None:
    reader = CountingReader()
    result = await manage.list_nodes(reader, limit=10)

    assert result["total"] == NODES
    assert result["items"][0]["revision"] == REVISION
    # 4441 次逐条读会退化成十几秒；批量读 + 复用 revision 只允许常数次调用。
    assert reader.read_calls == 0
    assert reader.read_many_calls == 1
    assert reader.total_calls <= 3


async def test_stats_reads_once_and_reuses_ids() -> None:
    reader = CountingReader()
    result = await manage.stats(reader)

    assert result["nodes"] == NODES
    assert reader.read_calls == 0
    assert reader.read_many_calls == 1
    assert reader.total_calls <= 3


async def test_audit_list_reads_once_and_reuses_ids() -> None:
    reader = CountingReader()
    await query.audit_list(reader)

    assert reader.read_calls == 0
    assert reader.read_many_calls == 1
    assert reader.total_calls <= 3


async def test_records_meta_projection_skips_body() -> None:
    reader = CountingReader()
    records = await query.records(reader, include_body=False)

    assert len(records) == NODES
    assert records[0].body == ""
    assert records[0].body_chars == len(BODY)
    assert records[0].revision == REVISION
