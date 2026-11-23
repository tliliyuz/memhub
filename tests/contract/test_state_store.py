"""运行态存储的契约：内存实现与 PG 实现必须给出同一组结论。

PG 用例只在 `MEMHUB_TEST_DB_URL` 存在时运行（本机没有库时跳过，不伪装通过）。
每个用例用独立 schema，跑完删掉，不污染库里的其他 schema：

    MEMHUB_TEST_DB_URL=postgresql://memhub_app@127.0.0.1/memhub_dev \
      pytest tests/contract/test_state_store.py -v
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from memhub.contract import BatchFile, Cursor, IngestRequest
from memhub.ingest.store import CursorConflict, MemoryStore, StateStore
from memhub.queue.rawstore import BatchTargetConflict

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)
DEVICE = str(uuid.uuid4())


def _batch(
    *,
    batch_id: str | None = None,
    path: str = "sessions/a.jsonl",
    content: str = "hello",
    from_offset: int = 0,
    source_rev: int = 0,
) -> IngestRequest:
    return IngestRequest(
        batch_id=batch_id or str(uuid.uuid4()),
        device_id=DEVICE,
        source_id="cc-sessions",
        source_type="sessions",
        project="example-kb",
        source_rev=source_rev,
        files=[
            BatchFile(
                path=path,
                from_offset=from_offset,
                to_offset=from_offset + len(content),
                mtime=NOW,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                content=content,
            )
        ],
    )


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[StateStore]:
    if request.param == "memory":
        memory = MemoryStore()
        await memory.register_device(DEVICE, name="test", platform="win32")
        yield memory
        return

    # ---- PG ----
    import psycopg
    from psycopg import sql

    from memhub.ingest.postgres import PostgresStore

    dsn = os.environ.get("MEMHUB_TEST_DB_URL", "")
    if not dsn:
        pytest.skip("MEMHUB_TEST_DB_URL 未设置；PG 契约未执行")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    pg_store = PostgresStore(dsn, schema=schema)
    try:
        await pg_store.migrate()
        await pg_store.register_device(DEVICE, name="test", platform="win32")
        yield pg_store
    finally:
        await pg_store.close()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)),
            )


async def test_unknown_device_is_not_registered(store: StateStore) -> None:
    assert await store.is_registered(DEVICE)
    assert not await store.is_registered(str(uuid.uuid4()))


async def test_first_push_advances_cursor(store: StateStore) -> None:
    result = await store.apply(_batch(content="hello"))
    assert (result.accepted, result.duplicates, result.replayed) == (1, 0, False)
    assert result.cursor.files == 1
    assert result.cursor.bytes == 5

    source_rev, files = await store.get_cursor(DEVICE, "cc-sessions")
    assert source_rev == 0
    assert [(file.path, file.offset) for file in files] == [("sessions/a.jsonl", 5)]


async def test_same_batch_is_replay_within_window(store: StateStore) -> None:
    batch_id = str(uuid.uuid4())
    first = await store.apply(_batch(batch_id=batch_id))
    second = await store.apply(_batch(batch_id=batch_id))
    assert first.replayed is False
    assert second.replayed is True
    assert (second.accepted, second.duplicates) == (first.accepted, first.duplicates)


async def test_replay_cannot_retarget_batch(store: StateStore) -> None:
    request = _batch()
    await store.apply(request)
    redirected = request.model_copy(update={"project": "other-kb", "files": []})
    with pytest.raises(BatchTargetConflict):
        await store.check_replay_target(redirected)
    with pytest.raises(BatchTargetConflict):
        await store.apply(redirected)
    replay = await store.check_replay_target(request)
    assert replay is not None and replay.replayed
    assert "_project" not in replay.model_dump()


async def test_offset_rollback_is_conflict(store: StateStore) -> None:
    await store.apply(_batch(content="hello"))
    with pytest.raises(CursorConflict) as excinfo:
        await store.apply(_batch(content="llo", from_offset=0))
    assert excinfo.value.expected_offset == 5


async def test_conflict_rolls_back_the_whole_batch(store: StateStore) -> None:
    """同一批里先进后出：冲突时前面那条文件的游标也不能留下。"""
    await store.apply(_batch(content="hello"))
    later = IngestRequest(
        batch_id=str(uuid.uuid4()),
        device_id=DEVICE,
        source_id="cc-sessions",
        source_type="sessions",
        files=[
            BatchFile(
                path="sessions/b.jsonl",
                from_offset=0,
                to_offset=3,
                mtime=NOW,
                sha256=hashlib.sha256(b"abc").hexdigest(),
                content="abc",
            ),
            BatchFile(
                path="sessions/a.jsonl",
                from_offset=0,
                to_offset=3,
                mtime=NOW,
                sha256=hashlib.sha256(b"xyz").hexdigest(),
                content="xyz",
            ),
        ],
    )
    with pytest.raises(CursorConflict):
        await store.apply(later)
    _, files = await store.get_cursor(DEVICE, "cc-sessions")
    assert [file.path for file in files] == ["sessions/a.jsonl"]


async def test_same_content_different_batch_is_duplicate(store: StateStore) -> None:
    await store.apply(_batch(content="hello"))
    # 换路径但内容 sha 相同：去重按 (source, sha)，不看路径。
    result = await store.apply(_batch(content="hello", path="sessions/copy.jsonl"))
    assert (result.accepted, result.duplicates) == (0, 1)


async def test_new_source_rev_allows_rescan(store: StateStore) -> None:
    await store.apply(_batch(content="hello world"))
    result = await store.apply(_batch(content="hello", from_offset=0, source_rev=1))
    assert result.accepted == 1
    source_rev, files = await store.get_cursor(DEVICE, "cc-sessions")
    assert source_rev == 1
    assert files[0].offset == 5


async def test_empty_cursor_for_unknown_source(store: StateStore) -> None:
    assert await store.get_cursor(DEVICE, "never-seen") == (0, [])
    assert await store.cursor_summary(DEVICE, "never-seen") == Cursor()


async def test_concurrent_same_batch_applies_once(store: StateStore) -> None:
    """并发重放：advisory lock / 单事务保证只应用一次。"""
    batch_id = str(uuid.uuid4())
    results = await asyncio.gather(
        store.apply(_batch(batch_id=batch_id)),
        store.apply(_batch(batch_id=batch_id)),
    )
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].accepted == results[1].accepted
