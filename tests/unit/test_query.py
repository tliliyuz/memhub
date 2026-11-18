"""检索组的只读行为。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memhub.contract import Edge, Kind, NodeFrontmatter, Predicate, Tier
from memhub.kb.query import QueryError, audit_list, read_node, related, search
from memhub.kb.store import KnowledgeStore

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _write(
    store: KnowledgeStore,
    node_id: str,
    *,
    title: str,
    kind: Kind = Kind.FACT,
    body: str = "",
    tags: list[str] | None = None,
    tier: Tier = Tier.CANDIDATE,
    confidence: float | None = None,
    updated_at: datetime | None = None,
) -> None:
    node = NodeFrontmatter(
        id=node_id,
        kind=kind,
        title=title,
        tier=tier,
        confidence=confidence,
        project=node_id.split("/")[0],
        tags=tags or [],
        created_at=NOW,
        updated_at=updated_at or NOW,
    )
    store.write(node_id, node, body)


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    _write(
        kb,
        "memhub/fact/proxy-502",
        title="HTTPX trust_env 导致代理 502",
        body="代理失败时先看 trust_env 是否被环境代理污染。",
        tags=["httpx", "proxy"],
    )
    _write(
        kb,
        "memhub/pitfall/no-proxy",
        title="不要在请求路径上放 Proxy",
        kind=Kind.PITFALL,
        body="Proxy 站会放大故障。",
        tags=["proxy"],
    )
    _write(
        kb,
        "other/fact/same-word",
        title="代理在另一个项目里的用法",
        body="这个节点只属于 other 项目。",
    )
    kb.append_edges(
        "memhub",
        [
            Edge(
                source="memhub/fact/proxy-502",
                predicate=Predicate.ABOUT,
                target="memhub/pitfall/no-proxy",
            )
        ],
        source_doc="session.jsonl",
    )
    return kb


def test_default_tier_is_canonical_and_hints_at_candidates(store: KnowledgeStore) -> None:
    response = search(store, "代理")
    assert response["results"] == []
    assert "候选" in response["hint"]


def test_tier_all_sees_candidates(store: KnowledgeStore) -> None:
    response = search(store, "代理", tier="all")
    ids = [item["id"] for item in response["results"]]
    assert "memhub/fact/proxy-502" in ids
    assert response["results"][0]["matched"] == "fts"
    assert response["results"][0]["tier"] == "candidate"


def test_chinese_without_spaces_still_matches(tmp_path: Path) -> None:
    # 没有空格的中文查询会被补成二元组，不必整句精确命中。
    kb = KnowledgeStore(tmp_path)
    _write(
        kb,
        "memhub/procedure/retry",
        title="网络重试",
        kind=Kind.PROCEDURE,
        body="网络重试需要退避抖动。",
    )
    response = search(kb, "重试退避", tier="all")
    assert [item["id"] for item in response["results"]] == ["memhub/procedure/retry"]


def test_project_and_kind_filters(store: KnowledgeStore) -> None:
    other = search(store, "代理", project="other", tier="all")
    assert [item["id"] for item in other["results"]] == ["other/fact/same-word"]

    pitfalls = search(store, "proxy", kinds=["pitfall"], tier="all")
    assert [item["id"] for item in pitfalls["results"]] == ["memhub/pitfall/no-proxy"]


def test_invalid_filters_are_rejected(store: KnowledgeStore) -> None:
    with pytest.raises(QueryError):
        search(store, "proxy", tier="everything")
    with pytest.raises(QueryError):
        search(store, "proxy", kinds=["unknown"])
    with pytest.raises(QueryError):
        related(store, "memhub/fact/proxy-502", predicates=["nope"])


def test_read_returns_both_edge_directions(store: KnowledgeStore) -> None:
    source = read_node(store, "memhub/fact/proxy-502")
    assert source["frontmatter"]["title"] == "HTTPX trust_env 导致代理 502"
    assert source["edges"]["out"] == [{"predicate": "about", "target": "memhub/pitfall/no-proxy"}]
    target = read_node(store, "memhub/pitfall/no-proxy")
    assert target["edges"]["in"] == [{"predicate": "about", "source": "memhub/fact/proxy-502"}]
    assert target["truncated"] is False


def test_read_rejects_unknown_and_traversal_ids(store: KnowledgeStore) -> None:
    with pytest.raises(QueryError):
        read_node(store, "memhub/fact/missing")
    with pytest.raises(QueryError):
        read_node(store, "../outside")


def test_related_walks_one_hop_and_filters_predicates(store: KnowledgeStore) -> None:
    graph = related(store, "memhub/pitfall/no-proxy")
    assert {node["id"] for node in graph["nodes"]} == {
        "memhub/pitfall/no-proxy",
        "memhub/fact/proxy-502",
    }
    assert graph["edges"][0]["predicate"] == "about"

    filtered = related(store, "memhub/pitfall/no-proxy", predicates=["depends_on"])
    assert [node["id"] for node in filtered["nodes"]] == ["memhub/pitfall/no-proxy"]
    assert filtered["edges"] == []


def test_audit_finds_contradiction_broken_orphan_and_low_confidence(
    store: KnowledgeStore,
) -> None:
    _write(
        store,
        "memhub/fact/weak",
        title="把握不大的结论",
        confidence=0.2,
    )
    store.append_edges(
        "memhub",
        [
            Edge(
                source="memhub/fact/proxy-502",
                predicate=Predicate.CONTRADICTS,
                target="memhub/fact/weak",
            ),
            Edge(
                source="memhub/fact/weak",
                predicate=Predicate.ABOUT,
                target="missing-node",
            ),
        ],
        source_doc="session.jsonl",
    )
    _write(store, "memhub/fact/orphan", title="没有人引用我")

    response = audit_list(store)
    types = {issue["type"] for issue in response["issues"]}
    assert {"contradiction", "broken_link", "orphan", "low_confidence"} <= types
    contradiction = next(issue for issue in response["issues"] if issue["type"] == "contradiction")
    assert set(contradiction["target"]) == {"memhub/fact/proxy-502", "memhub/fact/weak"}
    assert response["total"] == len(response["issues"])


def test_stale_needs_old_date_and_references(tmp_path: Path) -> None:
    kb = KnowledgeStore(tmp_path)
    old = NOW - timedelta(days=200)
    _write(kb, "memhub/fact/old", title="旧结论", updated_at=old)
    for index in range(3):
        _write(kb, f"memhub/fact/ref-{index}", title=f"引用 {index}")
        kb.append_edges(
            "memhub",
            [
                Edge(
                    source=f"memhub/fact/ref-{index}",
                    predicate=Predicate.ABOUT,
                    target="memhub/fact/old",
                )
            ],
            source_doc="session.jsonl",
        )
    issues = audit_list(kb)["issues"]
    stale = [issue for issue in issues if issue["type"] == "stale"]
    assert [issue["target"] for issue in stale] == ["memhub/fact/old"]
