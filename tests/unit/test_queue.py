"""提炼队列（ADR-0020）：去重、配额、领取/租约、终态与清理。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memhub.contract import BatchFile, IngestRequest
from memhub.ingest.store import MemoryStore
from memhub.queue.content import LocalContentStore
from memhub.queue.flow import enqueue_batch
from memhub.queue.identity import BatchTargetConflict
from memhub.queue.tasks import (
    DEFAULT_MAX_ATTEMPTS,
    MemoryQueue,
    QuotaExceeded,
    project_for,
)

NOW = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)


def _request(
    content: str,
    *,
    project: str = "example-kb",
    batch_id: str = "b-1",
    device_id: str = "dev-1",
    source_id: str = "cc-sessions",
    source_type: str = "sessions",
    path: str = "sessions/a.jsonl",
) -> IngestRequest:
    data = content.encode()
    return IngestRequest(
        batch_id=batch_id,
        device_id=device_id,
        source_id=source_id,
        source_type=source_type,
        project=project,
        files=[
            BatchFile(
                path=path,
                from_offset=0,
                to_offset=len(data),
                mtime=NOW,
                sha256=hashlib.sha256(data).hexdigest(),
                content=content,
            )
        ],
    )


async def test_enqueue_is_content_addressed() -> None:
    queue = MemoryQueue()
    first = await queue.enqueue(_request("hello"), producer="collector", limit=10_000)
    second = await queue.enqueue(
        _request("hello", batch_id="b-2", path="sessions/copy.jsonl"),
        producer="collector",
        limit=10_000,
    )

    assert (first.accepted, first.duplicates) == (1, 0)
    assert (second.accepted, second.duplicates) == (0, 1), "同一内容不重复入队"
    assert len(queue.rows) == 1


async def test_retargeting_content_is_a_conflict() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    with pytest.raises(BatchTargetConflict):
        await queue.check(_request("hello", project="other-kb"), producer="collector", limit=10_000)
    with pytest.raises(BatchTargetConflict):
        await queue.enqueue(
            _request("hello", project="other-kb"), producer="collector", limit=10_000
        )


async def test_quota_counts_only_new_bytes() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    replay = _request("hello", path="sessions/copy.jsonl")
    plan = await queue.check(replay, producer="collector", limit=5)
    assert plan.new_bytes == 0, "重放不占配额"

    with pytest.raises(QuotaExceeded) as excinfo:
        await queue.check(_request("a" * 10), producer="collector", limit=5)
    assert (excinfo.value.used, excinfo.value.limit, excinfo.value.incoming) == (5, 5, 10)


async def test_pending_bytes_excludes_finished_rows() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)
    assert await queue.pending_bytes() == 5

    [task] = await queue.claim()
    assert await queue.pending_bytes() == 5, "processing 仍占待提炼额度"
    await queue.complete(task)
    assert await queue.pending_bytes() == 0


async def test_claim_marks_processing_and_counts_attempts() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    [task] = await queue.claim(limit=1)
    assert (task.project, task.path, task.bytes, task.attempts) == (
        "example-kb",
        "sessions/a.jsonl",
        5,
        1,
    )
    assert await queue.claim() == [], "已领取的行不会再次返回"


async def test_expired_lease_is_reclaimed() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)
    await queue.claim()

    # 负租约让 cutoff 落在未来：等价于「领取后已超时」。
    [again] = await queue.claim(lease=timedelta(seconds=-1))
    assert again.attempts == 2


async def test_retry_requeues_until_limit_then_quarantines() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
        [task] = await queue.claim()
        assert task.attempts == attempt
        status = await queue.retry(task, f"boom {attempt}", max_attempts=DEFAULT_MAX_ATTEMPTS)
        expected = "pending_review" if attempt == DEFAULT_MAX_ATTEMPTS else "queued"
        assert status == expected

    assert await queue.claim() == [], "隔离后不再占用队列"
    progress = await queue.batch_progress("example-kb", "b-1")
    assert progress is not None
    assert (progress.pending_review, progress.errors) == (1, ("boom 3",))


async def test_review_is_permanent_and_release_does_not_spend_attempts() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    [task] = await queue.claim()
    await queue.release(task)
    [released] = await queue.claim()
    assert released.attempts == 1, "临时不可用不消耗失败次数"

    await queue.review(released, "target_inactive")
    assert await queue.claim() == []
    progress = await queue.batch_progress("example-kb", "b-1")
    assert progress is not None and progress.status == "pending_review"


async def test_batch_items_and_unknown_batch() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)

    items = await queue.batch_items("example-kb", "b-1")
    assert [(item.name, item.status, item.attempts) for item in items] == [
        ("sessions/a.jsonl", "queued", 0)
    ]
    assert await queue.batch_progress("example-kb", "nope") is None
    assert await queue.batch_project("nope") is None


async def test_batch_project_is_none_when_ambiguous() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello", batch_id="shared"), producer="collector", limit=10_000)
    await queue.enqueue(
        _request("other", project="other-kb", batch_id="shared"),
        producer="collector",
        limit=10_000,
    )

    assert await queue.batch_project("shared") is None


async def test_purge_counts_by_status_and_only_matching_source() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)
    await queue.enqueue(_request("other"), producer="collector", limit=10_000)
    await queue.enqueue(
        _request("kept", device_id="other-device"), producer="collector", limit=10_000
    )
    [first] = await queue.claim(limit=1)
    await queue.complete(first)

    counts = await queue.purge_source("dev-1", "cc-sessions")
    assert counts == {"processed": 1, "queued": 1}
    assert len(queue.rows) == 1, "别的设备不受影响"


async def test_trim_only_removes_old_processed_rows() -> None:
    queue = MemoryQueue()
    await queue.enqueue(_request("hello"), producer="collector", limit=10_000)
    [task] = await queue.claim()
    await queue.complete(task)

    assert await queue.trim(before=NOW - timedelta(days=1)) == 0, "未到保留期的行不能删"
    assert await queue.trim(before=datetime.now(UTC) + timedelta(minutes=1)) == 1


async def test_console_producer_identity_is_enforced() -> None:
    console = _request(
        "hello",
        device_id="kb-console",
        source_type="docs",
        source_id="example-kb",
        path="note.md",
    )
    assert project_for(console, "console") == "example-kb"
    with pytest.raises(BatchTargetConflict):
        project_for(console, "collector")  # 保留设备不能冒充采集器

    mismatched = _request(
        "hello",
        device_id="kb-console",
        source_type="docs",
        source_id="other-source",
    )
    with pytest.raises(BatchTargetConflict):
        project_for(mismatched, "console")


@pytest.mark.parametrize("project", ["auto", "../etc", ""])
async def test_invalid_project_is_a_target_conflict(project: str) -> None:
    with pytest.raises(BatchTargetConflict):
        project_for(_request("hello", project=project), "collector")


# ---- 入队流程：正文先于队列行，判重由队列给出 -----------------------------


async def _flow_env(tmp_path: Path) -> tuple[MemoryStore, LocalContentStore, MemoryQueue]:
    state = MemoryStore()
    await state.register_device("dev-1")
    return state, LocalContentStore(tmp_path / "content_store"), MemoryQueue()


async def test_enqueue_batch_writes_content_before_queue(tmp_path: Path) -> None:
    state, content, queue = await _flow_env(tmp_path)
    request = _request("hello")

    result = await enqueue_batch(state, queue, content, request, producer="collector", limit=10_000)

    assert (result.accepted, result.duplicates, result.replayed) == (1, 0, False)
    assert await content.get("example-kb", request.files[0].sha256) == "hello"
    [row] = queue.rows.values()
    assert (row.status, row.batch_id, row.size) == ("queued", "b-1", 5)


async def test_enqueue_batch_dedupes_across_batches(tmp_path: Path) -> None:
    state, content, queue = await _flow_env(tmp_path)
    await enqueue_batch(
        state, queue, content, _request("hello"), producer="collector", limit=10_000
    )
    again = await enqueue_batch(
        state,
        queue,
        content,
        _request("hello", batch_id="b-2", path="sessions/copy.jsonl"),
        producer="collector",
        limit=10_000,
    )

    assert (again.accepted, again.duplicates) == (0, 1)


async def test_enqueue_batch_rejects_retarget_after_queue_trim(tmp_path: Path) -> None:
    """队列行可能已被按天裁剪，正文仍在 TTL 内：仍要拦住换目标。"""
    state, content, queue = await _flow_env(tmp_path)
    request = _request("hello")
    await enqueue_batch(state, queue, content, request, producer="collector", limit=10_000)
    queue.rows.clear()  # 等价于 trim 掉 processed 行

    with pytest.raises(BatchTargetConflict):
        await enqueue_batch(
            state,
            queue,
            content,
            _request("hello", batch_id="b-2", project="other-kb"),
            producer="collector",
            limit=10_000,
        )
