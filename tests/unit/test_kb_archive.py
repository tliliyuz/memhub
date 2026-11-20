"""整库归档故障恢复与投影协调（仅临时样本）。"""

from pathlib import Path
from typing import Any

import anyio
import pytest

from memhub.kb import archive, catalog, manage
from memhub.kb.projection import save_projection
from memhub.kb.store import KnowledgeStore


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    root.mkdir()
    return KnowledgeStore(root)


async def test_archive_rolls_back_on_io_error(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await catalog.create_kb(store, kb_id="example")
    apply = archive._apply

    async def fail_at_marker(root: Path, step: archive.Step) -> None:
        if step.path == archive.MARKER and isinstance(step.after, bytes):
            raise OSError("test write failure")
        await apply(root, step)

    monkeypatch.setattr(archive, "_apply", fail_at_marker)
    with pytest.raises(OSError, match="test write failure"):
        await catalog.delete_kb(store, "example")
    assert (store.root / "example").is_dir()
    assert (await catalog.list_archives(store))["total"] == 0
    assert not (store.root / archive.PENDING).exists()


async def test_archive_rolls_back_on_cancellation(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await catalog.create_kb(store, kb_id="example")
    apply = archive._apply
    with anyio.CancelScope() as scope:

        async def cancel_after_removal(root: Path, step: archive.Step) -> None:
            await apply(root, step)
            if step.path == "example" and step.after is None:
                scope.cancel()
                await anyio.lowlevel.checkpoint()

        monkeypatch.setattr(archive, "_apply", cancel_after_removal)
        await catalog.delete_kb(store, "example")
    assert scope.cancelled_caught
    assert (store.root / "example").is_dir()
    assert not (store.root / archive.PENDING).exists()


async def test_resume_interrupted_archive_refuses_unknown_changes(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await catalog.create_kb(store, kb_id="example")
    apply = archive._apply

    async def fail_both_directions(root: Path, step: archive.Step) -> None:
        if step.path == "example":
            await apply(root, step)
            raise OSError("test interruption")
        await apply(root, step)

    monkeypatch.setattr(archive, "_apply", fail_both_directions)
    with pytest.raises(OSError, match="test interruption"):
        await catalog.delete_kb(store, "example")
    monkeypatch.setattr(archive, "_apply", apply)
    assert (store.root / archive.PENDING).is_file()
    with pytest.raises(manage.WriteDeferred):
        await catalog.create_kb(store, kb_id="other")
    with pytest.raises(manage.WriteDeferred):
        await save_projection(store, store.root.parent / "kg.json")
    registry = store.root / ".kbs.json"
    old = registry.read_bytes()
    registry.write_bytes(b'{"kbs": [], "extra": "test"}')
    with pytest.raises(manage.ConflictError):
        await archive.recover(store)
    assert registry.read_bytes() == b'{"kbs": [], "extra": "test"}'
    registry.write_bytes(old)
    assert await archive.recover(store)
    assert not await archive.recover(store)
    assert not (store.root / "example").exists()
    assert (await catalog.list_archives(store))["total"] == 1
    assert await archive.projection_dirty(store.root)


async def test_projection_clears_dirty_only_after_success(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await catalog.create_kb(store, kb_id="example")
    await catalog.delete_kb(store, "example")
    from memhub.kb import projection

    class Graph:
        def save_to_file(self, output: Path) -> None:
            output.write_text("{}", encoding="utf-8")

    async def build(_: KnowledgeStore) -> tuple[Any, projection.ProjectionReport]:
        return Graph(), projection.ProjectionReport()

    monkeypatch.setattr(projection, "build_graph", build)
    output = store.root.parent / "kg.json"
    await save_projection(store, output, clear_archive_dirty=True)
    assert output.is_file()
    assert not await archive.projection_dirty(store.root)


async def test_corrupt_snapshot_does_not_touch_live_data(store: KnowledgeStore) -> None:
    await catalog.create_kb(store, kb_id="example")
    result = await catalog.delete_kb(store, "example")
    snapshot = store.root / archive.ARCHIVES / result["archive_id"] / "snapshot.zip"
    with snapshot.open("ab") as handle:
        handle.write(b"unexpected bytes")
    registry = (store.root / ".kbs.json").read_bytes()
    with pytest.raises(manage.ConflictError, match="校验失败"):
        await catalog.restore_kb(store, result["archive_id"])
    assert (store.root / ".kbs.json").read_bytes() == registry
    assert not (store.root / "example").exists()
    assert not (store.root / archive.PENDING).exists()
    assert (await catalog.list_archives(store))["total"] == 1
