"""补两个回归：question 节点可落盘；游标汇总与明细一致。"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memhub.contract import SourceKind, SourceRef
from memhub.ingest.app import create_app
from memhub.kb.store import KnowledgeStore
from memhub.worker.merge import merge
from memhub.worker.schema import ExtractedNode, Extraction

DEVICE = str(uuid.uuid4())
TOKEN = "devtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _node(slug: str, kind: str, body: str = "内容") -> dict[str, object]:
    return {
        "kind": kind,
        "entity_kind": None,
        "title": slug,
        "slug": slug,
        "body": body,
        "tags": [],
        "confidence": 0.6,
    }


async def test_question_node_defaults_to_open(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    extraction = Extraction(
        nodes=[
            ExtractedNode.model_validate(_node("unresolved-vector-store", "question")),
            ExtractedNode.model_validate(_node("a-fact", "fact")),
        ]
    )
    report = await merge(
        store,
        extraction,
        project="demo",
        source=SourceRef(type=SourceKind.WIKI, ref="a.md"),
    )
    assert report.created == ["demo/question/unresolved-vector-store", "demo/fact/a-fact"]
    node, _ = await store.read("demo/question/unresolved-vector-store")
    assert node.status is not None and node.status.value == "open"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    knowledge = tmp_path / "knowledge"
    (knowledge / "example-kb").mkdir(parents=True)
    (knowledge / ".kbs.json").write_text('{"kbs":[{"id":"example-kb"}]}', encoding="utf-8")
    grants = tmp_path / "grants.json"
    grants.write_text(json.dumps({"devices": {DEVICE: ["example-kb"]}}), encoding="utf-8")
    monkeypatch.setenv("MEMHUB_ENV", "dev")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_INGEST_GRANTS_PATH", str(grants))
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    with TestClient(create_app()) as test_client:
        test_client.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "t", "platform": "win32"},
        )
        yield test_client


def test_cursor_summary_matches_file_details(client: TestClient) -> None:
    files = []
    for name, content in (("a.jsonl", "hello"), ("b.jsonl", "world!")):
        data = content.encode()
        files.append(
            {
                "path": name,
                "from_offset": 0,
                "to_offset": len(data),
                "mtime": datetime(2026, 11, 18, tzinfo=UTC).isoformat(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "content": content,
            }
        )
    response = client.post(
        "/ingest/raw",
        headers=AUTH,
        json={
            "batch_id": str(uuid.uuid4()),
            "device_id": DEVICE,
            "source_id": "s1",
            "source_type": "sessions",
            "project": "example-kb",
            "files": files,
        },
    )
    assert response.status_code == 200

    data = client.get(
        "/ingest/cursor", params={"device_id": DEVICE, "source_id": "s1"}, headers=AUTH
    ).json()["data"]
    assert data["cursor"]["files"] == len(data["files"]) == 2
    assert data["cursor"]["bytes"] == sum(item["offset"] for item in data["files"])
