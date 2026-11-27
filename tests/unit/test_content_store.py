"""正文存储（ADR-0020）：本地实现语义一致，ClickHouse 实现走压缩 HTTP。"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from anyio import Path as AsyncPath

from memhub.queue.content import (
    ClickHouseContentStore,
    ContentEntry,
    ContentUnavailable,
    LocalContentStore,
    NullContentStore,
)

NOW = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)


def _entry(content: str, *, project: str = "example-kb", sha: str | None = None) -> ContentEntry:
    import hashlib

    return ContentEntry(
        project=project,
        sha256=sha or hashlib.sha256(content.encode()).hexdigest(),
        device_id="dev-1",
        source_id="cc-sessions",
        source_type="sessions",
        batch_id="b-1",
        path="sessions/a.jsonl",
        from_offset=0,
        to_offset=len(content),
        mtime=NOW,
        producer="collector",
        content=content,
    )


# ---- 本地实现 -------------------------------------------------------------


async def test_local_put_is_content_addressed(tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "content_store")
    entry = _entry("hello")

    assert await store.put([entry]) == 1
    assert await store.put([entry]) == 0, "同一 (project, sha) 不重写"
    assert await store.get(entry.project, entry.sha256) == "hello"
    assert await store.get(entry.project, "0" * 64) is None
    await store.close()


async def test_local_existing_reports_project_and_source(tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "content_store")
    entry = _entry("hello")
    await store.put([entry])

    assert await store.existing(entry.device_id, entry.source_id, [entry.sha256]) == {
        entry.sha256: entry.project
    }
    # 另一个源同样 sha：内容仍算已存在，但它属于别的源。
    assert (await store.existing("other-device", "other-source", [entry.sha256])) == {}
    assert await store.existing(entry.device_id, entry.source_id, []) == {}


async def test_local_corrupt_payload_is_unavailable_not_missing(tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "content_store")
    entry = _entry("hello")
    await store.put([entry])
    target = store._path(entry.project, entry.sha256)
    await AsyncPath(target).write_text("{not json", encoding="utf-8")

    with pytest.raises(ContentUnavailable):
        await store.get(entry.project, entry.sha256)
    with pytest.raises(ContentUnavailable):
        await store.existing(entry.device_id, entry.source_id, [entry.sha256])


async def test_local_identity_mismatch_is_unavailable(tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "content_store")
    entry = _entry("hello")
    await store.put([entry])
    target = store._path(entry.project, entry.sha256)
    payload = json.loads(await AsyncPath(target).read_text(encoding="utf-8"))
    payload["project"] = "other-kb"
    await AsyncPath(target).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContentUnavailable, match="identity"):
        await store.get(entry.project, entry.sha256)


async def test_local_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    store = LocalContentStore(tmp_path / "content_store")
    await store.put([_entry("hello")])
    leftovers = [item async for item in AsyncPath(store.root).rglob("*.tmp")]
    assert leftovers == []


async def test_null_store_keeps_queue_moving_without_content() -> None:
    store = NullContentStore()
    entry = _entry("hello")

    assert await store.put([entry]) == 1
    assert await store.existing(entry.device_id, entry.source_id, [entry.sha256]) == {}
    assert await store.get(entry.project, entry.sha256) is None


# ---- ClickHouse 实现 ------------------------------------------------------


def _ch_store(handler: httpx.MockTransport) -> ClickHouseContentStore:
    return ClickHouseContentStore(
        "https://ch.example", user="memhub_rw", password="secret", transport=handler
    )


async def test_clickhouse_put_uses_gzip_and_user_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["params"] = dict(request.url.params)
        seen["user"] = request.headers.get("X-ClickHouse-User")
        seen["key"] = request.headers.get("X-ClickHouse-Key")
        seen["encoding"] = request.headers.get("Content-Encoding")
        seen["body"] = gzip.decompress(request.content)
        return httpx.Response(200, text="")

    store = _ch_store(httpx.MockTransport(handler))
    assert await store.put([_entry("hello")]) == 1
    await store.close()

    assert seen["method"] == "POST"
    params = seen["params"]
    assert isinstance(params, dict)
    assert "INSERT INTO `memhub_raw`.`raw_sessions` FORMAT JSONEachRow" in str(params["query"])
    assert params["database"] == "memhub_raw"
    assert seen["user"] == "memhub_rw"
    assert seen["key"] == "secret"
    assert seen["encoding"] == "gzip"
    body = seen["body"]
    assert isinstance(body, bytes)
    row = json.loads(body.decode("utf-8"))
    assert row["content"] == "hello"
    assert row["project"] == "example-kb"


async def test_clickhouse_read_negotiates_compression_without_decompress_param() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["accept"] = request.headers.get("Accept-Encoding")
        return httpx.Response(200, text=json.dumps({"content": "hello"}))

    store = _ch_store(httpx.MockTransport(handler))
    assert await store.get("example-kb", "a" * 64) == "hello"
    await store.close()

    params = seen["params"]
    assert isinstance(params, dict)
    assert params["enable_http_compression"] == "1"
    assert "decompress" not in params, "服务端按未压缩解析压缩体会报 UNKNOWN_CODEC"
    assert seen["accept"] == "gzip"


async def test_clickhouse_existing_maps_shas_to_projects() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        rows = [{"sha256": "b" * 64, "project": "example-kb"}]
        return httpx.Response(200, text="\n".join(json.dumps(row) for row in rows))

    store = _ch_store(httpx.MockTransport(handler))
    found = await store.existing("dev-1", "cc-sessions", ["b" * 64, "b" * 64])
    await store.close()

    assert found == {"b" * 64: "example-kb"}
    params = seen["params"]
    assert isinstance(params, dict)
    assert params["param_device"] == "dev-1"
    assert params["param_source"] == "cc-sessions"
    assert params["param_shas"] == f"['{'b' * 64}']", "重复 sha 只查一次；必须是单引号数组字面量"


async def test_clickhouse_existing_escapes_array_literal() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, text="")

    store = _ch_store(httpx.MockTransport(handler))
    await store.existing("dev-1", "cc-sessions", ["e\nf", "a'b", "c\\d"])
    await store.close()

    params = seen["params"]
    assert isinstance(params, dict)
    # ClickHouse 数组参数按字面量解析，字符串内的反斜杠、单引号与控制字符必须转义，
    # 否则会在服务端拆词或形成语法错误（26.9 实测 400）。
    assert params["param_shas"] == "['a\\'b', 'c\\\\d', 'e\\nf']"


async def test_clickhouse_http_error_is_unavailable_without_credentials() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server exploded")

    store = _ch_store(httpx.MockTransport(handler))
    with pytest.raises(ContentUnavailable, match="500"):
        await store.get("example-kb", "a" * 64)
    await store.close()


async def test_clickhouse_network_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tls down")

    store = _ch_store(httpx.MockTransport(handler))
    with pytest.raises(ContentUnavailable, match="ConnectError"):
        await store.put([_entry("hello")])
    await store.close()
