"""管理写操作：创建、修订号并发、废弃、归档删除、边编辑（异步 IO）。"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import anyio
import pytest
from anyio import Path as AsyncPath

from memhub.contract import Edge, Kind, Predicate, Tier
from memhub.kb import manage, proc
from memhub.kb.store import KnowledgeStore, ProjectMissing


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    await AsyncPath(root).mkdir()
    # 存储层不再隐式建库：测试里要先显式建好默认知识库目录。
    await AsyncPath(root / "memhub").mkdir()
    return KnowledgeStore(root)


def _draft(**overrides: object) -> manage.NodeDraft:
    data: dict[str, object] = {
        "kind": Kind.FACT,
        "title": "HTTPX trust_env 导致代理 502",
        "body": "代理失败时先看 trust_env。",
        "project": "memhub",
        "tags": ["httpx"],
    }
    data.update(overrides)
    return manage.NodeDraft(**data)  # type: ignore[arg-type]


async def test_create_generates_kebab_id_and_frontmatter(store: KnowledgeStore) -> None:
    result = await manage.create_node(store, _draft())

    assert result["id"] == "memhub/fact/httpx-trust-env-502"
    node, body = await store.read(result["id"])
    assert node.title == "HTTPX trust_env 导致代理 502"
    assert node.tier is Tier.CANDIDATE
    assert node.source[0].type.value == "manual"
    assert "trust_env" in body
    assert result["revision"] == await manage.node_revision(store, result["id"])


async def test_create_falls_back_to_random_slug_for_cjk_title(store: KnowledgeStore) -> None:
    result = await manage.create_node(store, _draft(title="纯中文标题"))
    node_id = result["id"]
    assert node_id.startswith("memhub/fact/n-")
    assert manage.slugify("纯中文标题") == ""


async def test_create_duplicate_is_conflict(store: KnowledgeStore) -> None:
    await manage.create_node(store, _draft(slug="same-slug"))
    with pytest.raises(manage.ConflictError):
        await manage.create_node(store, _draft(title="另一个标题", slug="same-slug"))


async def test_create_entity_without_entity_kind_is_invalid(store: KnowledgeStore) -> None:
    with pytest.raises(manage.InvalidError):
        await manage.create_node(store, _draft(kind=Kind.ENTITY, title="Some Service"))


async def test_update_requires_matching_revision(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    node_id = str(created["id"])
    revision = str(created["revision"])

    with pytest.raises(manage.ConflictError) as excinfo:
        await manage.update_node(
            store, node_id, expected_revision="deadbeef", patch=manage.NodePatch(title="新标题")
        )
    assert excinfo.value.data["current"] == revision

    updated = await manage.update_node(
        store, node_id, expected_revision=revision, patch=manage.NodePatch(title="新标题")
    )
    assert updated["revision"] != revision
    node, body = await store.read(node_id)
    assert node.title == "新标题"
    assert body.startswith("代理失败")


async def test_update_to_deprecated_without_superseded_by_is_invalid(
    store: KnowledgeStore,
) -> None:
    created = await manage.create_node(store, _draft())
    with pytest.raises(manage.InvalidError):
        await manage.update_node(
            store,
            str(created["id"]),
            expected_revision=str(created["revision"]),
            patch=manage.NodePatch(tier=Tier.DEPRECATED),
        )


async def test_deprecate_sets_tier_and_appends_reason(store: KnowledgeStore) -> None:
    old = await manage.create_node(store, _draft(slug="old"))
    new = await manage.create_node(store, _draft(title="新版做法", slug="new"))

    result = await manage.deprecate_node(
        store, str(old["id"]), superseded_by=str(new["id"]), reason="已被新流程替代"
    )

    node, body = await store.read(str(old["id"]))
    assert node.tier is Tier.DEPRECATED
    assert node.superseded_by == new["id"]
    assert "废弃说明" in body
    assert result["revision"] == await manage.node_revision(store, str(old["id"]))


async def test_deprecate_rejects_unknown_superseded_by(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    with pytest.raises(manage.InvalidError):
        await manage.deprecate_node(store, str(created["id"]), superseded_by="memhub/fact/nope")


async def test_delete_archives_and_removes_incident_edges(store: KnowledgeStore) -> None:
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B", slug="b"))
    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )

    result = await manage.delete_node(
        store, str(b["id"]), expected_revision=str(b["revision"]), reason="重复"
    )

    assert result["removed_edges"] == 1
    assert not await store.exists(str(b["id"]))
    trash = await manage.list_trash(store)
    assert trash["total"] == 1
    assert trash["items"][0]["id"] == b["id"]

    restored = await manage.restore_node(store, str(result["trash"]))
    assert restored["id"] == b["id"]
    assert await store.exists(str(b["id"]))


async def test_deleted_node_does_not_reappear_as_trash_pseudo_node(
    store: KnowledgeStore,
) -> None:
    """归档文件仍是 markdown：list_ids 不跳过 `_trash/` 的话，删除过的节点会以
    `_trash/<时间戳>/<原 id>` 伪节点身份回到投影和图谱里（线上踩过）。"""
    created = await manage.create_node(store, _draft())
    await manage.delete_node(store, str(created["id"]), expected_revision=str(created["revision"]))
    assert await store.list_ids() == []
    assert await AsyncPath(store.root / "_trash").is_dir()


async def test_delete_rejects_stale_revision(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    with pytest.raises(manage.ConflictError):
        await manage.delete_node(store, str(created["id"]), expected_revision="stale")


async def test_restore_refuses_when_node_reappeared(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    deleted = await manage.delete_node(
        store, str(created["id"]), expected_revision=str(created["revision"])
    )
    await manage.create_node(store, _draft(slug=str(created["id"]).rsplit("/", 1)[-1]))
    with pytest.raises(manage.ConflictError):
        await manage.restore_node(store, str(deleted["trash"]))


async def test_create_node_refuses_missing_project(store: KnowledgeStore) -> None:
    with pytest.raises(ProjectMissing):
        await manage.create_node(store, _draft(project="ghost"))

    assert not await AsyncPath(store.root / "ghost").exists()


async def test_restore_does_not_recreate_missing_project_directory(
    store: KnowledgeStore,
) -> None:
    await AsyncPath(store.root / "doomed").mkdir()
    created = await manage.create_node(store, _draft(project="doomed"))
    deleted = await manage.delete_node(
        store, str(created["id"]), expected_revision=str(created["revision"])
    )
    await AsyncPath(store.root / "doomed" / "fact").rmdir()
    await AsyncPath(store.root / "doomed").rmdir()

    with pytest.raises(ProjectMissing):
        await manage.restore_node(store, str(deleted["trash"]))

    assert not await AsyncPath(store.root / "doomed").exists()


async def test_replace_out_edges_rewrites_only_source_side(store: KnowledgeStore) -> None:
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B", slug="b"))
    c = await manage.create_node(store, _draft(title="C", slug="c"))

    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [
            Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"])),
            Edge(source=str(b["id"]), predicate=Predicate.RELATED_TO, target=str(c["id"])),
        ][:1],
    )
    result = await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.DEPENDS_ON, target=str(c["id"]))],
    )
    assert result["added"] == 1

    detail = await manage.get_node(store, str(a["id"]))
    assert [edge["target"] for edge in detail["edges"]["out"]] == [c["id"]]
    # b 的出边不受影响
    assert (await manage.get_node(store, str(b["id"])))["edges"]["out"] == []


async def test_replace_out_edges_rechecks_source_after_waiting_for_lock(
    store: KnowledgeStore,
) -> None:
    created = await manage.create_node(store, _draft())
    node_id = str(created["id"])
    project = store.root / "memhub"
    archived = store.root / "_kb_archives" / "memhub"
    marker = AsyncPath(store.root / "_kb_archives" / "blocked" / "memhub")
    await marker.parent.mkdir(parents=True)
    # Writer 会在持锁者完成归档后进入临界区，不能使用等待前读取的节点。
    result: list[manage.ConflictError] = []

    async def replace_edges() -> None:
        try:
            await manage.replace_out_edges(
                store,
                node_id,
                [Edge(source=node_id, predicate=Predicate.RELATED_TO, target="next")],
            )
        except manage.ConflictError as exc:
            result.append(exc)

    async with anyio.create_task_group() as tasks, manage.write_lock(store.root):
        tasks.start_soon(replace_edges)
        await anyio.sleep(0.1)
        await AsyncPath(project).rename(archived)
        await marker.touch()
    assert result and type(result[0]).__name__ == "WriteDeferred"
    assert not await AsyncPath(project).exists()


async def test_replace_out_edges_rejects_foreign_source(store: KnowledgeStore) -> None:
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B", slug="b"))
    with pytest.raises(manage.InvalidError):
        await manage.replace_out_edges(
            store,
            str(a["id"]),
            [Edge(source=str(b["id"]), predicate=Predicate.RELATED_TO, target=str(a["id"]))],
        )


async def test_list_nodes_filters_and_pages(store: KnowledgeStore) -> None:
    await manage.create_node(store, _draft(slug="one", title="代理 502 排查"))
    await manage.create_node(
        store,
        _draft(
            slug="two",
            title="夜间运行窗口",
            body="凌晨两点前跑完。",
            kind=Kind.PROCEDURE,
            tags=["ops"],
        ),
    )

    everything = await manage.list_nodes(store)
    assert everything["total"] == 2

    facts = await manage.list_nodes(store, kind="fact")
    assert [item["id"] for item in facts["items"]] == ["memhub/fact/one"]

    tagged = await manage.list_nodes(store, tag="ops")
    assert [item["id"] for item in tagged["items"]] == ["memhub/procedure/two"]

    searched = await manage.list_nodes(store, q="代理")
    assert [item["id"] for item in searched["items"]] == ["memhub/fact/one"]

    page = await manage.list_nodes(store, limit=1, offset=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1


async def test_stats_counts_kinds_tiers_and_orphans(store: KnowledgeStore) -> None:
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B", slug="b", kind=Kind.PITFALL))
    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )

    stats = await manage.stats(store)
    assert stats["nodes"] == 2
    assert stats["edges"] == 1
    assert stats["orphans"] == 0
    assert stats["by_kind"] == {"fact": 1, "pitfall": 1}


@pytest.mark.parametrize("nested", [False, True])
async def test_git_commit_excludes_runtime_files_but_keeps_archive_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    root = tmp_path / "knowledge" if nested else tmp_path
    await AsyncPath(root).mkdir(exist_ok=True)
    await manage._git(tmp_path, ["init"], timeout=10)
    archive_id = "a" * 32
    runtime = {
        ".memhub-write.lock",
        manage.LOCK_NAME,
        "_kb_archives/pending.json",
        "_kb_archives/projection-dirty",
        "_kb_archives/.orphan.tmp",
        f"_kb_archives/{archive_id}/.orphan.tmp",
        f"_kb_archives/{archive_id}/{'b' * 32}.zip",
    }
    tracked = {
        "active/fact/example.md",
        "_kb_archives/blocked/demo",
        f"_kb_archives/{archive_id}/active.json",
        f"_kb_archives/{archive_id}/snapshot.zip",
    }
    for relative in runtime | tracked:
        path = AsyncPath(root / relative)
        await path.parent.mkdir(exist_ok=True, parents=True)
        await path.touch()

    git = manage._git

    async def stage_only_git(
        repo: Path, args: list[str], *, timeout: float
    ) -> tuple[int, bytes, bytes]:
        if args[0] in {"commit", "rev-parse"}:
            return 0, b"test", b""
        return await git(repo, args, timeout=timeout)

    monkeypatch.setattr(manage, "_git", stage_only_git)
    assert await manage._git_commit(root, "test") == "test"
    _, stdout, _ = await git(tmp_path, ["ls-files"], timeout=10)
    assert set(stdout.decode().splitlines()) == {
        (root.relative_to(tmp_path) / relative).as_posix() for relative in tracked
    }


async def test_revision_is_content_addressed(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    path = store.path_for(str(created["id"]))
    before = await manage.revision_of(path)
    text = await AsyncPath(path).read_text(encoding="utf-8")
    await AsyncPath(path).write_text(text + "\n额外一行\n", encoding="utf-8")
    assert await manage.revision_of(path) != before


async def test_write_lock_is_stable_and_ignores_legacy_file(store: KnowledgeStore) -> None:
    legacy = store.root / ".memhub-write.lock"
    await AsyncPath(legacy).write_text("old lock", encoding="utf-8")
    async with manage.write_lock(store.root, timeout=0.1):
        assert await AsyncPath(store.root / manage.LOCK_NAME).is_file()
    assert await AsyncPath(legacy).read_text(encoding="utf-8") == "old lock"
    assert await AsyncPath(store.root / manage.LOCK_NAME).is_file()
    async with manage.write_lock(store.root, timeout=0):
        pass


async def test_write_lock_never_steals_from_live_process_and_survives_its_death(
    store: KnowledgeStore,
) -> None:
    ready = store.root / "ready"
    script = """
import asyncio
import os
import sys
from pathlib import Path
from memhub.kb.manage import write_lock

async def main():
    async with write_lock(Path(sys.argv[1])):
        ready = Path(sys.argv[2])
        temp = ready.with_suffix('.tmp')
        temp.write_text(str(os.getpid()))
        temp.replace(ready)
        await asyncio.sleep(20)

asyncio.run(main())
"""
    child = await proc.spawn([sys.executable, "-c", script, str(store.root), str(ready)])
    pid = None
    try:
        with anyio.fail_after(10):
            while not await AsyncPath(ready).exists():
                assert proc.exit_code(child) is None
                await anyio.sleep(0.01)
            # Windows venv 的启动器和持锁的 Python 可能是不同进程。
            pid = int(await AsyncPath(ready).read_text())
        lock = store.root / manage.LOCK_NAME
        await anyio.to_thread.run_sync(os.utime, lock, (0, 0))
        with pytest.raises(manage.WriteDeferred, match="其他进程写入"):
            async with manage.write_lock(store.root, timeout=0.1):
                pytest.fail("不能接管仍被活进程持有的锁")
    finally:
        if pid is None:
            proc.kill(child)
        elif proc.exit_code(child) is None:
            os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
        await anyio.to_thread.run_sync(child.wait, 5)

    assert await AsyncPath(lock).is_file()
    async with manage.write_lock(store.root, timeout=0.1):
        pass


async def test_write_lock_releases_when_holder_is_cancelled(store: KnowledgeStore) -> None:
    acquired = anyio.Event()

    async def hold_lock() -> None:
        async with manage.write_lock(store.root):
            acquired.set()
            await anyio.sleep_forever()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(hold_lock)
        await acquired.wait()
        tasks.cancel_scope.cancel()

    async with manage.write_lock(store.root, timeout=0):
        pass


async def test_write_lock_blocks_pending_journal_but_allows_recovery(store: KnowledgeStore) -> None:
    pending = AsyncPath(store.root / "_kb_archives" / "pending.json")
    await pending.parent.mkdir()
    await pending.write_text("unfinished", encoding="utf-8")

    with pytest.raises(manage.ConflictError) as exc:
        async with manage.write_lock(store.root):
            pytest.fail("事务日志存在时，普通写入不能继续")
    assert type(exc.value).__name__ == "WriteDeferred"

    async with manage.write_lock(store.root, recovery=True):
        assert await pending.exists()
        await pending.unlink()
    async with manage.write_lock(store.root, timeout=0):
        pass


async def test_archived_project_cannot_be_recreated_by_node_writes(store: KnowledgeStore) -> None:
    created = await manage.create_node(store, _draft())
    deleted = await manage.delete_node(
        store, str(created["id"]), expected_revision=str(created["revision"])
    )
    marker = AsyncPath(store.root / "_kb_archives" / "blocked" / "memhub")
    await marker.parent.mkdir(parents=True)
    await marker.touch()

    with pytest.raises(manage.ConflictError) as exc:
        await manage.create_node(store, _draft(slug="new"))
    assert type(exc.value).__name__ == "WriteDeferred"
    with pytest.raises(manage.ConflictError) as exc:
        await manage.restore_node(store, str(deleted["trash"]))
    assert type(exc.value).__name__ == "WriteDeferred"
    assert not await store.exists(str(created["id"]))
    assert (await manage.list_trash(store))["total"] == 1

    await AsyncPath(store.root / "other").mkdir()
    await manage.create_node(store, _draft(project="other"))
    await marker.unlink()
    await manage.restore_node(store, str(deleted["trash"]))
    assert await store.exists(str(created["id"]))


async def test_list_trash_filters_and_pages(store: KnowledgeStore) -> None:
    for kb_id in ("alpha", "beta"):
        await AsyncPath(store.root / kb_id).mkdir()
    ids: list[str] = []
    for project, title, slug in [
        ("alpha", "Alpha 事实", "alpha-fact"),
        ("beta", "Beta 事实", "beta-fact"),
        ("beta", "Beta 次要", "beta-minor"),
    ]:
        created = await manage.create_node(store, _draft(project=project, title=title, slug=slug))
        ids.append(str(created["id"]))
    a, b, c = ids
    for node_id in (a, b, c):
        revision = str(await manage.node_revision(store, node_id))
        await manage.delete_node(store, node_id, expected_revision=revision, reason="test")

    everything = await manage.list_trash(store, limit=500)
    assert everything["total"] == 3 and everything["total_all"] == 3

    by_project = await manage.list_trash(store, limit=500, project="beta")
    assert by_project["total"] == 2
    assert {item["id"] for item in by_project["items"]} == {b, c}
    assert by_project["total_all"] == 3

    hits = await manage.list_trash(store, limit=500, q="alpha")
    assert hits["total"] == 1 and hits["items"][0]["id"] == a

    page = await manage.list_trash(store, limit=1, offset=1, project="beta")
    assert len(page["items"]) == 1 and page["offset"] == 1
    assert page["items"][0]["id"] == b  # 按路径倒序：beta-minor 在前，翻页后是 beta-fact
    assert page["total"] == 2  # total 是过滤后的总数，不是本页条数
