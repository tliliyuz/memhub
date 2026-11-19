"""raw_store 落盘：内容寻址、幂等、原子写（异步 IO）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import BatchFile, IngestRequest
from memhub.queue.rawstore import (
    QuotaExceeded,
    RawStoreQuota,
    batch_dir,
    estimate_new_bytes,
    save_batch,
    tree_size,
)

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)


def _request(
    content: str, *, path: str = "sessions/a.jsonl", device: str = "dev-1"
) -> IngestRequest:
    return IngestRequest(
        batch_id="b-1",
        device_id=device,
        source_id="cc-sessions",
        source_type="sessions",
        files=[
            BatchFile(
                path=path,
                from_offset=0,
                to_offset=len(content),
                mtime=NOW,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                content=content,
            )
        ],
    )


async def test_writes_content_addressed_file(tmp_path: Path) -> None:
    request = _request("hello")
    assert await save_batch(tmp_path, request) == 1
    sha = request.files[0].sha256
    target = batch_dir(tmp_path, "dev-1", "cc-sessions") / sha[:2] / f"{sha}.json"
    assert await AsyncPath(target).is_file()
    payload = json.loads(await AsyncPath(target).read_text(encoding="utf-8"))
    assert payload["content"] == "hello"
    assert payload["path"] == "sessions/a.jsonl"
    assert payload["mtime"] == NOW.isoformat()


async def test_second_push_of_same_content_is_noop(tmp_path: Path) -> None:
    assert await save_batch(tmp_path, _request("hello")) == 1
    assert await save_batch(tmp_path, _request("hello", path="sessions/copy.jsonl")) == 0


async def test_unsafe_ids_cannot_escape_the_data_dir(tmp_path: Path) -> None:
    await save_batch(tmp_path, _request("hello", device="../../etc"))
    root = (tmp_path / "raw_store").resolve()
    async for item in AsyncPath(root).rglob("*.json"):
        assert root in Path(item).resolve().parents


async def test_failed_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    request = _request("hello")
    await save_batch(tmp_path, request)
    leftovers = [item async for item in AsyncPath(tmp_path).rglob("*.tmp")]
    assert leftovers == []


async def test_quota_counts_only_new_content(tmp_path: Path) -> None:
    """已落盘的 sha 重放时不该占配额，否则客户端会被永久卡在一条已收下的数据上。"""
    request = _request("hello")
    await save_batch(tmp_path, request)
    assert await estimate_new_bytes(tmp_path, request) == 0
    assert await estimate_new_bytes(tmp_path, _request("hello", path="sessions/other.jsonl")) == 0
    assert await estimate_new_bytes(tmp_path, _request("different")) > 0


async def test_quota_uses_actual_tree_size(tmp_path: Path) -> None:
    await save_batch(tmp_path, _request("hello"))
    expected = 0
    async for item in AsyncPath(tmp_path / "raw_store").rglob("*"):
        if await item.is_file():
            expected += (await item.stat()).st_size
    assert expected > 0
    assert await tree_size(tmp_path / "raw_store") == expected


async def test_quota_rejects_when_full_and_tracks_writes(tmp_path: Path) -> None:
    quota = RawStoreQuota(tmp_path / "raw_store", 1000, refresh_seconds=3600)
    first = await estimate_new_bytes(tmp_path, _request("hello"))
    await quota.check(first)
    await save_batch(tmp_path, _request("hello"))
    await quota.record(first)

    with pytest.raises(QuotaExceeded) as excinfo:
        await quota.check(2000)
    assert excinfo.value.limit == 1000
    assert excinfo.value.used >= first

    # 重放已收下的内容（增量 0）仍应放行。
    await quota.check(0)


async def test_quota_rescans_after_invalidate(tmp_path: Path) -> None:
    quota = RawStoreQuota(tmp_path / "raw_store", 10_000, refresh_seconds=3600)
    assert await quota.used_bytes() == 0
    await save_batch(tmp_path, _request("hello"))
    await quota.invalidate()
    assert await quota.used_bytes() > 0
