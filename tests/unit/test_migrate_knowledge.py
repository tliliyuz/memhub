"""一次性迁移（markdown → PG）的解析半段：只读扫描、不写库、不删文件。

验收条件来自 `docs/plans/kb-pg-migration-spec.md` §5 第 1–5、7 步：
- 记录集字段名按目标表列名（`kb_nodes` / `kb_projects` / `kb_edges` / `kb_archives`）；
- 未登记库导入而不是跳过，`.kbs.json` 与目录集合不一致要给出差异；
- 归档数据（`_trash`、`_kb_archives`）单独探测，快照字节与哈希可校验；
- 悬空边原样保留并报告，不因校验丢弃；
- `--verify-only` 需要的逐节点内容哈希必须由解析结果直接算出。

fixture 全部是 `tests/fixtures/knowledge_tree` 下的合成数据，不读仓库真实 `knowledge/`。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from memhub.kb import catalog, manage
from memhub.kb.migrate import MigrationPlan, node_revision, parse_tree
from memhub.kb.store import KnowledgeStore

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_tree"
REVISION_RE = re.compile(r"^[0-9a-f]{16}$")

KB_NODE_COLUMNS = {
    "id",
    "project",
    "kind",
    "entity_kind",
    "title",
    "tier",
    "confidence",
    "tags",
    "body",
    "source",
    "valid_from",
    "valid_until",
    "supersedes",
    "superseded_by",
    "deprecated_reason",
    "occurred_at",
    "decided_at",
    "status",
    "created_at",
    "updated_at",
    "archived_at",
    "revision",
}
KB_PROJECT_COLUMNS = {
    "id",
    "name",
    "description",
    "revision",
    "created_at",
    "updated_at",
    "archived_at",
}
KB_EDGE_COLUMNS = {"project", "source", "predicate", "target", "source_doc", "created_at"}
KB_ARCHIVE_COLUMNS = {
    "archive_id",
    "project",
    "status",
    "snapshot",
    "archived_count",
    "removed_edges",
    "actor",
    "deleted_at",
    "created_at",
}


def _tree(tmp_path: Path, name: str = "knowledge") -> Path:
    root = tmp_path / name
    shutil.copytree(FIXTURE, root)
    return root


async def test_records_use_target_table_column_names(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))

    assert {(p["id"], p["name"]) for p in plan.projects} >= {("demo", "演示库")}
    for project in plan.projects:
        assert set(project) == KB_PROJECT_COLUMNS
    for node in plan.nodes:
        assert set(node) == KB_NODE_COLUMNS
    for edge in plan.edges:
        assert set(edge) == KB_EDGE_COLUMNS
    for archive_row in plan.archives:
        assert KB_ARCHIVE_COLUMNS <= set(archive_row)


async def test_node_body_excludes_frontmatter_and_keeps_chinese(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    alpha = next(node for node in plan.nodes if node["id"] == "demo/fact/alpha")

    assert alpha["body"].startswith("# 合成事实 Alpha")
    assert "第一段：合成样本的正文。" in alpha["body"]
    assert "\n\n第二段" in alpha["body"]
    assert "title:" not in alpha["body"]
    assert alpha["project"] == "demo"
    assert alpha["kind"] == "fact"
    assert alpha["tags"] == ["alpha", "合成"]
    assert alpha["source"][0]["type"] == "session"


async def test_unregistered_directory_is_imported_as_project(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))

    orphan = next(project for project in plan.projects if project["id"] == "orphan")
    assert orphan["name"] == "orphan"
    assert orphan["description"] == ""
    assert plan.diff.unregistered_projects == ("orphan",)
    # 未登记库的节点必须带归属迁入，不能因为没登记就丢掉。
    assert "orphan/fact/gamma" in {node["id"] for node in plan.nodes}


async def test_registered_kb_without_directory_is_reported(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))

    assert plan.diff.missing_projects == ("gone",)
    assert "gone" not in {project["id"] for project in plan.projects}


async def test_dangling_edge_is_kept_and_reported(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))

    assert len(plan.edges) == 2
    dangling = plan.diff.dangling_edges
    assert len(dangling) == 1
    assert dangling[0]["target"] == "nowhere"
    assert dangling[0]["source"] == "demo/fact/alpha"
    # 悬空边仍要以原样进 kb_edges。
    assert any(edge["target"] == "nowhere" for edge in plan.edges)


async def test_revision_is_stable_16_hex_and_content_addressed(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    alpha = next(node for node in plan.nodes if node["id"] == "demo/fact/alpha")

    assert REVISION_RE.fullmatch(alpha["revision"])
    assert node_revision(alpha) == alpha["revision"]
    again = await parse_tree(_tree(tmp_path, "knowledge-again"))
    assert (
        next(n for n in again.nodes if n["id"] == "demo/fact/alpha")["revision"]
        == (alpha["revision"])
    )

    changed = {**alpha, "body": alpha["body"] + "追加一行。"}
    assert node_revision(changed) != alpha["revision"]


async def test_supersedes_maps_to_target_column_without_data_loss(tmp_path: Path) -> None:
    """`supersedes` 在 `kb_nodes` 有正式列，必须原样落到行里且参与内容哈希。"""
    root = _tree(tmp_path)
    path = root / "demo" / "fact" / "alpha.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("supersedes: []", "supersedes:\n- demo/fact/old"),
        encoding="utf-8",
    )

    plan = await parse_tree(root)

    alpha = next(node for node in plan.nodes if node["id"] == "demo/fact/alpha")
    assert alpha["supersedes"] == ["demo/fact/old"]
    assert plan.diff.unsupported_fields == (), "已有正式列，不应再报数据损失"
    assert node_revision({**alpha, "supersedes": []}) != alpha["revision"]


async def test_trash_nodes_are_archived_not_dropped(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    store = KnowledgeStore(root)
    revision = await manage.node_revision(store, "demo/fact/alpha")
    assert revision is not None
    await manage.delete_node(
        store, "demo/fact/alpha", expected_revision=revision, reason="合成删除", actor="ui:test"
    )

    plan = await parse_tree(root)

    archived = [node for node in plan.nodes if node["archived_at"] is not None]
    assert [node["id"] for node in archived] == ["demo/fact/alpha"]
    assert str(archived[0]["archived_at"]).startswith("20")
    assert plan.diff.invalid_trash == ()


async def test_archive_snapshot_is_read_and_verified(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    store = KnowledgeStore(root)
    await catalog.delete_kb(store, "demo", actor="ui:test")

    plan = await parse_tree(root)

    assert len(plan.archives) == 1
    archive = plan.archives[0]
    assert archive["project"] == "demo"
    assert archive["status"] == "active"
    assert archive["archived_count"] == 2
    # 快照字节要与 active.json 记录的 sha256 一致，verify-only 才能比对。
    assert hashlib.sha256(archive["snapshot"]).hexdigest() == archive["snapshot_sha256"]
    assert archive["snapshot"]
    # 归档库不应残留在活跃 nodes 里。
    assert "demo/fact/alpha" not in {node["id"] for node in plan.nodes}


async def test_invalid_node_is_reported_with_path_not_raised(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    bad = root / "demo" / "entity" / "bad.md"
    bad.parent.mkdir()
    bad.write_text(
        "---\n"
        "created_at: '2026-01-06T00:00:00Z'\n"
        "id: demo/entity/bad\n"
        "kind: entity\n"
        "project: demo\n"
        "title: 缺 entity_kind\n"
        "updated_at: '2026-01-06T00:00:00Z'\n"
        "---\n\n正文。\n",
        encoding="utf-8",
    )

    plan = await parse_tree(root)

    assert [item["node_id"] for item in plan.diff.invalid_nodes] == ["demo/entity/bad"]
    assert "demo/entity/bad" not in {node["id"] for node in plan.nodes}


async def test_recognisable_but_unknown_file_is_reported(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "demo" / "fact" / "notes.txt").write_text("x\n", encoding="utf-8")

    plan = await parse_tree(root)

    assert plan.diff.unknown_files == ("demo/fact/notes.txt",)


async def test_plan_is_a_frozen_snapshot_with_json_ready_diff(tmp_path: Path) -> None:
    plan = await parse_tree(_tree(tmp_path))
    assert isinstance(plan, MigrationPlan)
    payload = plan.diff.as_dict()
    assert payload["unregistered_projects"] == ["orphan"]
    assert payload["missing_projects"] == ["gone"]
    assert json.dumps(payload)


async def test_pending_archive_blocks_migration(tmp_path: Path) -> None:
    """归档事务未完成（`pending.json` 在）时禁止迁移，否则快照与真源不一致。"""
    root = _tree(tmp_path)
    pending = root / "_kb_archives" / "pending.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text("{}\n", encoding="utf-8")

    plan = await parse_tree(root)

    assert plan.diff.pending_archive is True
    assert plan.blocking is True


@pytest.mark.parametrize("name", ["demo", "orphan"])
async def test_project_rows_are_deterministically_revised(tmp_path: Path, name: str) -> None:
    plan = await parse_tree(_tree(tmp_path))
    project = next(item for item in plan.projects if item["id"] == name)
    assert REVISION_RE.fullmatch(project["revision"])


async def test_nodes_of_unregistered_directory_keep_their_project(tmp_path: Path) -> None:
    """未登记库必须建 project 行，否则 `kb_nodes.project` 的外键无主、节点无处可落。"""
    plan = await parse_tree(_tree(tmp_path))
    project_ids = {item["id"] for item in plan.projects}

    for node in plan.nodes:
        assert node["project"] in project_ids, node["id"]


async def test_registry_entry_created_at_is_carried_over(tmp_path: Path) -> None:
    """`.kbs.json` 里已有的 created_at 是真源事实，迁移不得用扫描时刻覆盖它。"""
    root = _tree(tmp_path)
    (root / ".kbs.json").write_text(
        json.dumps(
            {
                "kbs": [
                    {
                        "id": "demo",
                        "name": "演示库",
                        "description": "迁移解析用的合成样本",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    plan = await parse_tree(root)
    demo = next(item for item in plan.projects if item["id"] == "demo")

    assert demo["created_at"].year == 2026
    assert demo["created_at"].month == 1
    assert demo["created_at"].day == 1


async def test_pending_archive_is_reported_but_plan_still_inspects(tmp_path: Path) -> None:
    """`pending.json` 只阻断写库，不阻断只读统计：dry-run 仍要看得到计数与差异。"""
    root = _tree(tmp_path)
    (root / "_kb_archives").mkdir(parents=True, exist_ok=True)
    (root / "_kb_archives" / "pending.json").write_text("{}\n", encoding="utf-8")

    plan = await parse_tree(root)

    assert plan.blocking is True
    assert {node["id"] for node in plan.nodes} >= {"demo/fact/alpha", "orphan/fact/gamma"}


async def test_edge_created_at_is_populated_not_null(tmp_path: Path) -> None:
    """`kb_edges.created_at` 是 not null；解析侧必须给出确定值，不能留空等写库时才定。"""
    plan = await parse_tree(_tree(tmp_path))

    for edge in plan.edges:
        assert edge["created_at"] is not None
