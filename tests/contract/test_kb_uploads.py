"""知识库上传契约：kb-api 只调 ingest 内部接口，不直写正文或队列。

上传的文件先由 kb-api 做格式校验，再整批 POST `/internal/enqueue`；状态读
`GET /internal/queue/{batch_id}`，按队列行映射成管理台的 queued/processed/failed。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from memhub.kb.api import create_app
from memhub.kb.errors import TargetUnavailable
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.uploads import KbUploads
from memhub.queue.identity import CONSOLE_DEVICE

TOKEN = "internal-test-token"


class _Projects:
    """只回答目标状态；上传路径不读节点，不依赖 PG。"""

    def __init__(self, active: set[str], unavailable: set[str] | None = None) -> None:
        self.active = active
        self.unavailable = unavailable or set()

    async def project_status(self, project: str) -> str:
        if project in self.unavailable:
            raise TargetUnavailable("registry_unavailable")
        return "active" if project in self.active else "unregistered"


class _Ingest:
    """ingest 内部接口的替身：记录入队请求，返回可改写的批次进度。"""

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.batches: dict[str, dict[str, Any]] = {}
        self.tokens: list[str | None] = []
        self.fail: bool = False
        self.enqueue_error: tuple[int, dict[str, Any]] | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("ingest down", request=request)
        self.tokens.append(request.headers.get("Authorization"))
        if request.method == "POST" and request.url.path == "/internal/enqueue":
            body = cast(dict[str, Any], json.loads(request.content))
            if self.enqueue_error is not None:
                status, payload = self.enqueue_error
                return httpx.Response(status, json=payload)
            self.enqueued.append(body)
            files = [
                {
                    "name": item["path"],
                    "sha256": item["sha256"],
                    "status": "queued",
                    "attempts": 0,
                }
                for item in body["files"]
            ]
            batch = {
                "batch_id": body["batch_id"],
                "project": body["project"],
                "total": len(files),
                "created_at": "2026-11-27T02:00:00+00:00",
                "files": files,
                "counts": {
                    "queued": len(files),
                    "processing": 0,
                    "processed": 0,
                    "pending_review": 0,
                },
            }
            self.batches[body["batch_id"]] = batch
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": body["batch_id"],
                        "accepted": len(files),
                        "duplicates": 0,
                        "replayed": False,
                    },
                },
            )
        if request.method == "GET" and request.url.path.startswith("/internal/queue/"):
            batch_id = request.url.path.rsplit("/", 1)[-1]
            batch = self.batches.get(batch_id)
            if batch is None:
                return httpx.Response(
                    404, json={"code": 1011, "message": "batch not found", "data": {}}
                )
            return httpx.Response(200, json={"code": 0, "data": batch})
        return httpx.Response(404, json={"code": 1011, "message": "not found", "data": {}})


@pytest.fixture
def ingest() -> _Ingest:
    return _Ingest()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, ingest: _Ingest) -> Iterator[TestClient]:
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)
    monkeypatch.delenv("MEMHUB_INGEST_URL", raising=False)
    monkeypatch.delenv("MEMHUB_INTERNAL_TOKEN", raising=False)
    projects = _Projects({"memory-hub"})
    uploads = KbUploads("http://ingest.internal", TOKEN, transport=ingest.transport())
    with TestClient(
        create_app(
            store=cast(PgKnowledgeStore, projects),
            uploads=uploads,
        )
    ) as client:
        yield client


def _upload(
    client: TestClient,
    files: list[tuple[str, bytes]] | None = None,
    *,
    project: str = "memory-hub",
) -> httpx.Response:
    payload = files or [("note.md", "# 沙盒上传\n\n内容一行。".encode())]
    return client.post(
        "/api/v1/kb/uploads",
        data={"project": project},
        files=[("files", (name, body, "text/plain")) for name, body in payload],
    )


def _created(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 201, response.text
    data = response.json()
    assert isinstance(data, dict)
    return data


def test_upload_enqueues_into_ingest_and_reports_queued(env: TestClient, ingest: _Ingest) -> None:
    created = _created(_upload(env))

    assert created["queued"] is True
    assert created["rejected"] == []
    accepted = created["accepted"]
    assert isinstance(accepted, list) and len(accepted) == 1
    sha = str(accepted[0]["sha256"])

    assert len(ingest.enqueued) == 1
    body = ingest.enqueued[0]
    assert body["device_id"] == CONSOLE_DEVICE
    assert body["source_type"] == "docs"
    assert body["source_id"] == "memory-hub"
    assert body["project"] == "memory-hub"
    assert body["batch_id"] == created["batch_id"]
    [file] = body["files"]
    assert (file["path"], file["sha256"], file["from_offset"]) == ("note.md", sha, 0)
    assert file["content"] == "# 沙盒上传\n\n内容一行。"
    assert ingest.tokens == [f"Bearer {TOKEN}"]

    status = env.get(f"/api/v1/kb/uploads/{created['batch_id']}")
    assert status.status_code == 200
    result = status.json()
    assert result["project"] == "memory-hub"
    assert result["counts"] == {"queued": 1, "processed": 0, "failed": 0, "missing": 0}
    assert result["files"][0]["status"] == "queued"


def test_status_follows_queue_rows(env: TestClient, ingest: _Ingest) -> None:
    batch_id = str(_created(_upload(env))["batch_id"])
    batch = ingest.batches[batch_id]
    item = batch["files"][0]

    item["status"] = "processing"
    batch["counts"] = {"queued": 0, "processing": 1, "processed": 0, "pending_review": 0}
    body = env.get(f"/api/v1/kb/uploads/{batch_id}").json()
    assert body["files"][0]["status"] == "queued", "processing 对管理台仍显示为排队中"
    assert body["counts"]["queued"] == 1

    item["status"] = "processed"
    batch["counts"] = {"queued": 0, "processing": 0, "processed": 1, "pending_review": 0}
    body = env.get(f"/api/v1/kb/uploads/{batch_id}").json()
    assert body["files"][0]["status"] == "processed"

    item["status"] = "pending_review"
    item["attempts"] = 3
    batch["counts"] = {"queued": 0, "processing": 0, "processed": 0, "pending_review": 1}
    body = env.get(f"/api/v1/kb/uploads/{batch_id}").json()
    assert body["files"][0]["status"] == "failed"
    assert body["files"][0]["attempts"] == 3
    assert body["counts"]["failed"] == 1


def test_rejects_unsupported_and_keeps_valid_files(env: TestClient, ingest: _Ingest) -> None:
    created = _created(_upload(env, [("note.md", b"# ok"), ("scan.pdf", b"%PDF-1.7")]))
    accepted = created["accepted"]
    assert isinstance(accepted, list) and len(accepted) == 1
    assert created["rejected"] == [{"name": "scan.pdf", "reason": "unsupported_type"}]
    assert len(ingest.enqueued) == 1
    assert [item["path"] for item in ingest.enqueued[0]["files"]] == ["note.md"]


def test_rejects_when_nothing_acceptable(env: TestClient, ingest: _Ingest) -> None:
    response = _upload(env, [("big.bin", b"\x00\x01")])
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 1012
    assert body["data"]["rejected"] == [{"name": "big.bin", "reason": "unsupported_type"}]
    assert ingest.enqueued == [], "整批被拒时不能打扰 ingest"


def test_rejects_invalid_project_and_too_many_files(env: TestClient, ingest: _Ingest) -> None:
    bad_project = _upload(env, project="../escape")
    assert bad_project.status_code == 422
    assert bad_project.json()["code"] == 1012

    too_many = _upload(env, [(f"n{index}.md", b"# n") for index in range(21)])
    assert too_many.status_code == 422
    assert too_many.json()["code"] == 1012
    assert ingest.enqueued == []


def test_unregistered_project_is_not_upload_target(env: TestClient, ingest: _Ingest) -> None:
    response = _upload(env, project="unregistered")
    assert response.status_code == 404
    assert response.json()["code"] == 1011
    assert ingest.enqueued == []


def test_unknown_batch_and_invalid_id_are_404(env: TestClient) -> None:
    not_found = env.get("/api/v1/kb/uploads/deadbeefdeadbeefdeadbeefdeadbeef")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == 1011

    invalid_id = env.get("/api/v1/kb/uploads/..%2F..%2Fetc")
    assert invalid_id.status_code == 404


def test_queue_full_returns_1013(env: TestClient, ingest: _Ingest) -> None:
    ingest.enqueue_error = (
        503,
        {
            "code": 1013,
            "message": "queue quota exceeded",
            "data": {"used_bytes": 10, "limit_bytes": 1, "incoming_bytes": 5},
        },
    )
    response = _upload(env)
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == 1013
    assert body["data"] == {"used": 10, "limit": 1, "incoming": 5}


def test_ingest_unreachable_is_503(env: TestClient, ingest: _Ingest) -> None:
    ingest.fail = True
    response = _upload(env)
    assert response.status_code == 503
    assert response.json()["code"] == 2001


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/kb/uploads"),
        ("get", "/api/v1/kb/uploads/deadbeefdeadbeefdeadbeefdeadbeef"),
    ],
)
def test_upload_disabled_without_ingest_credentials(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.delenv("MEMHUB_INGEST_URL", raising=False)
    monkeypatch.delenv("MEMHUB_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)
    projects = _Projects({"memory-hub"})
    with TestClient(create_app(store=cast(PgKnowledgeStore, projects))) as client:
        if method == "post":
            response = client.post(
                path,
                data={"project": "memory-hub"},
                files=[("files", ("a.md", b"# a", "text/plain"))],
            )
        else:
            response = client.get(path)
        assert response.status_code == 503
        assert response.json()["code"] == 2001


def test_target_registry_unavailable_does_not_enqueue(
    monkeypatch: pytest.MonkeyPatch, ingest: _Ingest
) -> None:
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)
    projects = _Projects({"memory-hub"}, unavailable={"memory-hub"})
    uploads = KbUploads("http://ingest.internal", TOKEN, transport=ingest.transport())
    with TestClient(create_app(store=cast(PgKnowledgeStore, projects), uploads=uploads)) as client:
        response = _upload(client)
    assert response.status_code == 503
    assert ingest.enqueued == []


def test_same_content_keeps_same_sha(env: TestClient, ingest: _Ingest) -> None:
    first = _created(_upload(env))
    second = _created(_upload(env))

    assert first["accepted"][0]["sha256"] == second["accepted"][0]["sha256"]
    assert len(ingest.enqueued) == 2, "内容判重由 ingest 负责，kb-api 不缓存清单"
    assert ingest.enqueued[0]["files"][0]["sha256"] == ingest.enqueued[1]["files"][0]["sha256"]
