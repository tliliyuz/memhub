"""采集 API 契约：信封、鉴权、游标冲突、幂等。"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from memhub.ingest.app import create_app

DEVICE = str(uuid.uuid4())
TOKEN = "devtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    with TestClient(create_app()) as test_client:
        response = test_client.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        assert response.status_code == 200
        yield test_client


def _file(path: str, content: str, from_offset: int = 0) -> dict[str, object]:
    data = content.encode()
    return {
        "path": path,
        "from_offset": from_offset,
        "to_offset": from_offset + len(data),
        "mtime": datetime(2026, 11, 18, tzinfo=UTC).isoformat(),
        "sha256": __import__("hashlib").sha256(data).hexdigest(),
        "content": content,
    }


def _push(
    client: TestClient,
    files: list[dict[str, object]],
    *,
    source_rev: int = 0,
    batch_id: str | None = None,
) -> tuple[int, dict[str, object]]:
    response = client.post(
        "/ingest/raw",
        headers=AUTH,
        json={
            "batch_id": batch_id or str(uuid.uuid4()),
            "device_id": DEVICE,
            "source_id": "cc-sessions",
            "source_type": "sessions",
            "source_rev": source_rev,
            "files": files,
        },
    )
    return response.status_code, response.json()


def test_cursor_is_empty_before_first_push(client: TestClient) -> None:
    response = client.get(
        "/ingest/cursor",
        params={"device_id": DEVICE, "source_id": "cc-sessions"},
        headers=AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["files"] == []
    assert body["data"]["source_rev"] == 0


def test_push_advances_cursor(client: TestClient) -> None:
    status, body = _push(client, [_file("a.jsonl", "hello")])
    assert status == 200
    assert body["data"]["accepted"] == 1

    response = client.get(
        "/ingest/cursor",
        params={"device_id": DEVICE, "source_id": "cc-sessions"},
        headers=AUTH,
    )
    files = response.json()["data"]["files"]
    assert files[0]["path"] == "a.jsonl"
    assert files[0]["offset"] == 5


def test_replayed_batch_returns_previous_result(client: TestClient) -> None:
    batch_id = str(uuid.uuid4())
    first = _push(client, [_file("a.jsonl", "hello")], batch_id=batch_id)
    second = _push(client, [_file("a.jsonl", "hello")], batch_id=batch_id)
    assert first[1]["data"]["replayed"] is False
    assert second[1]["data"]["replayed"] is True
    assert second[1]["data"]["accepted"] == first[1]["data"]["accepted"]


def test_offset_rollback_is_conflict(client: TestClient) -> None:
    _push(client, [_file("a.jsonl", "hello")])
    status, body = _push(client, [_file("a.jsonl", "llo", from_offset=0)])
    assert status == 409
    assert body["code"] == 1004
    assert body["data"]["expected_offset"] == 5


def test_new_source_rev_allows_rescan(client: TestClient) -> None:
    _push(client, [_file("a.jsonl", "hello world")])
    status, body = _push(client, [_file("a.jsonl", "hello", from_offset=0)], source_rev=1)
    assert status == 200
    assert body["data"]["accepted"] == 1


def test_missing_token_is_401(client: TestClient) -> None:
    response = client.get(
        "/ingest/cursor",
        params={"device_id": DEVICE, "source_id": "cc-sessions"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == 1001


def test_unregistered_device_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/ingest/cursor",
        params={"device_id": "someone-else", "source_id": "cc-sessions"},
        headers=AUTH,
    )
    assert response.status_code == 403
    assert response.json()["code"] == 1002


def test_binary_content_is_rejected(client: TestClient) -> None:
    status, body = _push(client, [_file("a.bin", "abc\x00def")])
    assert status == 422
    assert body["code"] == 1006
