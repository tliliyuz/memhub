"""旧本机队列一次性导入（DEVELOPMENT §9.2）：校验、幂等、断点重跑与核验。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memhub.queue.backfill import run_backfill
from memhub.queue.content import LocalContentStore
from memhub.queue.tasks import MemoryQueue

NOW = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)


def _write_record(
    data_dir: Path,
    *,
    content: str = "hello",
    project: str = "kb-one",
    producer: str = "collector",
    device_id: str = "dev-1",
    source_id: str = "cc-sessions",
    source_type: str = "sessions",
    batch_id: str = "b-1",
    path: str = "sessions/a.jsonl",
    root: str = "raw_store",
    name_sha: str | None = None,
    sha: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Path:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    target_dir = data_dir / root / device_id / source_id / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    record = payload or {
        "producer": producer,
        "device_id": device_id,
        "source_id": source_id,
        "source_type": source_type,
        "project": project,
        "batch_id": batch_id,
        "path": path,
        "from_offset": 0,
        "to_offset": len(content.encode("utf-8")),
        "mtime": NOW.isoformat(),
        "sha256": digest if sha is None else sha,
        "content": content,
    }
    target = target_dir / f"{name_sha or digest}.json"
    target.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


async def _run(
    data_dir: Path,
    *,
    dry_run: bool = False,
    verify_only: bool = False,
    queue: MemoryQueue | None = None,
    content: LocalContentStore | None = None,
):
    return await run_backfill(
        data_dir,
        queue=queue or MemoryQueue(),
        content=content or LocalContentStore(data_dir / "content_store"),
        limit=1024**3,
        dry_run=dry_run,
        verify_only=verify_only,
    )


async def test_dry_run_validates_without_writing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_record(data_dir)
    _write_record(data_dir, content="tampered", name_sha=hashlib.sha256(b"hello").hexdigest())
    (data_dir / "raw_store" / "dev-1" / "cc-sessions" / "zz").mkdir(parents=True)
    (data_dir / "raw_store" / "dev-1" / "cc-sessions" / "zz" / "broken.json").write_text(
        "{not json", encoding="utf-8"
    )
    queue = MemoryQueue()

    report = await _run(data_dir, dry_run=True, queue=queue)

    assert report.scanned == 3
    assert report.valid == 1
    assert report.imported == 1
    assert report.duplicates == 0
    assert len(report.failures) == 2
    assert any("broken.json" in item for item in report.failures)
    assert await queue.batch_items("kb-one", "b-1") == []


async def test_import_is_idempotent_and_keeps_source_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    source = _write_record(data_dir)
    queue = MemoryQueue()
    content = LocalContentStore(data_dir / "content_store")

    first = await _run(data_dir, queue=queue, content=content)
    second = await _run(data_dir, queue=queue, content=content)

    assert (first.imported, first.duplicates, first.failures) == (1, 0, ())
    assert (second.imported, second.duplicates, second.failures) == (0, 1, ())
    assert source.exists()
    items = await queue.batch_items("kb-one", "b-1")
    assert [(item.sha256, item.status) for item in items] == [
        (hashlib.sha256(b"hello").hexdigest(), "queued")
    ]
    stored = await content.get("kb-one", hashlib.sha256(b"hello").hexdigest())
    assert stored == "hello"


async def test_processed_and_review_roots_are_reported_not_imported(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_record(data_dir, content="processed", root="processed_raw")
    _write_record(data_dir, content="review", root="pending_review")
    queue = MemoryQueue()

    report = await _run(data_dir, queue=queue)

    assert report.imported == 0
    assert report.processed_raw == 1
    assert report.pending_review == 1
    assert await queue.batch_items("kb-one", "b-1") == []


async def test_invalid_target_is_reported_and_other_groups_still_import(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_record(data_dir, content="console", producer="console", device_id="dev-1")
    _write_record(data_dir, content="ok", project="kb-two", source_id="other")

    report = await _run(data_dir)

    assert report.imported == 1
    assert len(report.failures) == 1
    assert "dev-1" in report.failures[0]


async def test_verify_only_detects_missing_and_passes_after_import(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_record(data_dir)
    queue = MemoryQueue()
    content = LocalContentStore(data_dir / "content_store")
    before = await _run(data_dir, verify_only=True, queue=queue, content=content)
    assert before.verified == 0
    assert len(before.failures) == 1

    imported = await _run(data_dir, queue=queue, content=content)
    assert imported.imported == 1
    after = await _run(data_dir, verify_only=True, queue=queue, content=content)
    assert after.verified == 1
    assert after.failures == ()
