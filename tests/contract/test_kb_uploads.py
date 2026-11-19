"""知识库上传的契约行为：落盘复用、状态推导、拒绝与配额。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from memhub.kb.api import create_app


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    data_dir = tmp_path / "data"
    (data_dir / "raw_store").mkdir(parents=True)

    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kb" / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(data_dir))
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)
    monkeypatch.delenv("MEMHUB_KB_GRAPH_PORT", raising=False)

    with TestClient(create_app()) as client:
        yield client, data_dir


def _upload(
    client: TestClient,
    project: str = "memory-hub",
    files: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    payload = files or [("note.md", "# 沙盒上传\n\n内容一行。".encode())]
    response = client.post(
        "/api/v1/kb/uploads",
        data={"project": project},
        files=[("files", (name, body, "text/plain")) for name, body in payload],
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert isinstance(data, dict)
    return data


def _manifest(data_dir: Path, batch_id: str) -> dict[str, Any]:
    text = (data_dir / "uploads" / f"{batch_id}.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


def test_upload_lands_in_raw_store_and_reports_queued(env: tuple[TestClient, Path]) -> None:
    client, data_dir = env
    created = _upload(client)

    batch_id = str(created["batch_id"])
    assert created["queued"] is True
    assert created["rejected"] == []
    accepted = created["accepted"]
    assert isinstance(accepted, list) and len(accepted) == 1
    sha = str(accepted[0]["sha256"])

    landed = data_dir / "raw_store" / "kb-console" / "memory-hub" / sha[:2] / f"{sha}.json"
    assert landed.is_file()
    payload = json.loads(landed.read_text(encoding="utf-8"))
    assert payload["source_type"] == "docs"
    assert payload["path"] == "note.md"
    assert payload["batch_id"] == batch_id

    status = client.get(f"/api/v1/kb/uploads/{batch_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["project"] == "memory-hub"
    assert body["counts"] == {"queued": 1, "processed": 0, "failed": 0, "missing": 0}
    assert body["files"][0]["status"] == "queued"


def test_status_follows_worker_moves(env: tuple[TestClient, Path]) -> None:
    client, data_dir = env
    created = _upload(client)
    batch_id = str(created["batch_id"])
    manifest = _manifest(data_dir, batch_id)
    files = manifest["files"]
    assert isinstance(files, list)
    rel = str(files[0]["rel"])

    processed = data_dir / "processed_raw" / rel
    processed.parent.mkdir(parents=True, exist_ok=True)
    processed.write_text("{}", encoding="utf-8")
    assert client.get(f"/api/v1/kb/uploads/{batch_id}").json()["files"][0]["status"] == "processed"

    processed.unlink()
    failures = data_dir / "state" / "failures.json"
    failures.parent.mkdir(parents=True, exist_ok=True)
    failures.write_text(json.dumps({rel: 2}), encoding="utf-8")
    body = client.get(f"/api/v1/kb/uploads/{batch_id}").json()
    assert body["files"][0]["status"] == "failed"
    assert body["files"][0]["attempts"] == 2

    failures.unlink()
    quarantined = data_dir / "pending_review" / rel
    quarantined.parent.mkdir(parents=True, exist_ok=True)
    quarantined.write_text("{}", encoding="utf-8")
    body = client.get(f"/api/v1/kb/uploads/{batch_id}").json()
    assert body["files"][0]["status"] == "failed"
    assert body["counts"]["failed"] == 1


def test_rejects_unsupported_and_keeps_valid_files(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    created = _upload(
        client,
        files=[("note.md", b"# ok"), ("scan.pdf", b"%PDF-1.7")],
    )
    accepted = created["accepted"]
    assert isinstance(accepted, list) and len(accepted) == 1
    assert created["rejected"] == [{"name": "scan.pdf", "reason": "unsupported_type"}]


def test_rejects_when_nothing_acceptable(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    response = client.post(
        "/api/v1/kb/uploads",
        data={"project": "memory-hub"},
        files=[("files", ("big.bin", b"\x00\x01", "application/octet-stream"))],
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 1012
    assert body["data"]["rejected"] == [{"name": "big.bin", "reason": "unsupported_type"}]


def test_rejects_invalid_project_and_too_many_files(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    bad_project = client.post(
        "/api/v1/kb/uploads",
        data={"project": "../escape"},
        files=[("files", ("a.md", b"# a", "text/plain"))],
    )
    assert bad_project.status_code == 422
    assert bad_project.json()["code"] == 1012

    files = [(f"n{index}.md", b"# n") for index in range(21)]
    too_many = client.post(
        "/api/v1/kb/uploads",
        data={"project": "memory-hub"},
        files=[("files", (name, body, "text/plain")) for name, body in files],
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == 1012


def test_queue_full_returns_1013(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    data_dir = tmp_path / "data"
    (data_dir / "raw_store").mkdir(parents=True)
    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kb" / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "1")
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/kb/uploads",
            data={"project": "memory-hub"},
            files=[("files", ("a.md", b"# a", "text/plain"))],
        )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == 1013
    assert body["data"]["limit"] == 1


def test_unknown_batch_and_missing_data_dir(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    not_found = client.get("/api/v1/kb/uploads/deadbeefdeadbeefdeadbeefdeadbeef")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == 1011

    invalid_id = client.get("/api/v1/kb/uploads/..%2F..%2Fetc")
    assert invalid_id.status_code == 404


def test_upload_disabled_without_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kb" / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/kb/uploads",
            data={"project": "memory-hub"},
            files=[("files", ("a.md", b"# a", "text/plain"))],
        )
        assert response.status_code == 503
        assert response.json()["code"] == 2001


def test_same_content_is_content_addressed(env: tuple[TestClient, Path]) -> None:
    client, data_dir = env
    first = _upload(client)
    second = _upload(client)

    first_file = first["accepted"][0]
    second_file = second["accepted"][0]
    assert first_file["sha256"] == second_file["sha256"]
    shas = list((data_dir / "raw_store").rglob("*.json"))
    assert len(shas) == 1
