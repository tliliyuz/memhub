"""`--verify-only` 的比对逻辑（规格 §5 第 7 步）：逐节点内容哈希 + 逐边三元组。

这一层不连库：比对函数只吃「磁盘侧解析结果」与「库内侧读出结果」两份纯数据，
让差异判定可以脱离 PG 单测；真正的读库在 `read_stored`，由契约测试覆盖。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from memhub.kb.migrate import MigrationPlan, parse_tree
from memhub.kb.migrate_db import StoredKnowledge, diff_plan

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_tree"


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    shutil.copytree(FIXTURE, root)
    return root


def _stored_from(plan: MigrationPlan) -> StoredKnowledge:
    return StoredKnowledge(
        projects={project["id"]: dict(project) for project in plan.projects},
        nodes={node["id"]: dict(node) for node in plan.nodes},
        edges={(edge["source"], edge["predicate"], edge["target"]) for edge in plan.edges},
        archives={row["archive_id"]: row["snapshot_sha256"] for row in plan.archives},
    )


async def test_identical_store_has_no_differences(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))

    diff = diff_plan(plan, _stored_from(plan))

    assert diff.ok, diff.as_dict()
    assert diff.as_dict()["changed_nodes"] == []


async def test_changed_body_is_reported_per_node(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    stored = _stored_from(plan)
    alpha = dict(stored.nodes["demo/fact/alpha"])
    alpha["body"] = alpha["body"] + "库内被改过。"
    stored = StoredKnowledge(
        projects=stored.projects,
        nodes={**stored.nodes, alpha["id"]: alpha},
        edges=stored.edges,
        archives=stored.archives,
    )

    diff = diff_plan(plan, stored)

    assert not diff.ok
    assert [item["node_id"] for item in diff.changed_nodes] == ["demo/fact/alpha"]
    assert diff.changed_nodes[0]["db_revision"] != diff.changed_nodes[0]["disk_revision"]


async def test_missing_and_extra_nodes_are_named(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    stored = _stored_from(plan)
    nodes = dict(stored.nodes)
    del nodes["orphan/fact/gamma"]
    nodes["demo/fact/ghost"] = dict(next(iter(nodes.values())))
    nodes["demo/fact/ghost"]["id"] = "demo/fact/ghost"
    stored = StoredKnowledge(
        projects=stored.projects, nodes=nodes, edges=stored.edges, archives=stored.archives
    )

    diff = diff_plan(plan, stored)

    assert diff.missing_nodes == ("orphan/fact/gamma",)
    assert diff.extra_nodes == ("demo/fact/ghost",)


async def test_missing_and_extra_edges_are_reported_as_triples(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    stored = _stored_from(plan)
    edges = {edge for edge in stored.edges if edge[2] != "nowhere"}
    edges.add(("demo/fact/alpha", "related_to", "demo/fact/beta"))
    stored = StoredKnowledge(
        projects=stored.projects, nodes=stored.nodes, edges=edges, archives=stored.archives
    )

    diff = diff_plan(plan, stored)

    assert [item["target"] for item in diff.missing_edges] == ["nowhere"]
    assert [item["target"] for item in diff.extra_edges] == ["demo/fact/beta"]


async def test_missing_project_is_reported(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    stored = _stored_from(plan)
    projects = {key: value for key, value in stored.projects.items() if key != "orphan"}
    stored = StoredKnowledge(
        projects=projects, nodes=stored.nodes, edges=stored.edges, archives=stored.archives
    )

    diff = diff_plan(plan, stored)

    assert diff.missing_projects == ("orphan",)


async def test_archive_hash_mismatch_is_reported(tmp_path: Path) -> None:
    from memhub.kb import catalog
    from memhub.kb.store import KnowledgeStore

    root = _tree(tmp_path)
    await catalog.delete_kb(KnowledgeStore(root), "demo", actor="ui:test")
    plan = await parse_tree(root)
    stored = _stored_from(plan)
    stored = StoredKnowledge(
        projects=stored.projects,
        nodes=stored.nodes,
        edges=stored.edges,
        archives={archive_id: "0" * 64 for archive_id in stored.archives},
    )

    diff = diff_plan(plan, stored, archives="migrate")

    assert diff.ok is False
    assert diff.archive_mismatches
    assert diff.as_dict()["archive_mismatches"][0]["archive_id"] == plan.archives[0]["archive_id"]


async def test_archive_comparison_is_skipped_unless_requested(tmp_path: Path) -> None:
    from memhub.kb import catalog
    from memhub.kb.store import KnowledgeStore

    root = _tree(tmp_path)
    await catalog.delete_kb(KnowledgeStore(root), "demo", actor="ui:test")
    plan = await parse_tree(root)
    stored = _stored_from(plan)
    stored = StoredKnowledge(
        projects=stored.projects, nodes=stored.nodes, edges=stored.edges, archives={}
    )

    diff = diff_plan(plan, stored)

    assert diff.ok
    assert diff.archive_mismatches == ()
