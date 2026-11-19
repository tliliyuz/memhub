"""知识库管理 API 的契约行为（状态码、错误信封、路由顺序、SPA 回退）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memhub.kb.api import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>memhub</title>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kb" / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(web))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.delenv("MEMHUB_KB_GRAPH_PORT", raising=False)

    with TestClient(create_app()) as test_client:
        yield test_client


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "fact",
        "title": "HTTPX trust_env 导致代理 502",
        "body": "先看 trust_env。",
        "project": "memhub",
        "tags": ["httpx"],
    }
    payload.update(overrides)
    response = client.post("/api/v1/kb/nodes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_stats(client: TestClient) -> None:
    _create(client)
    health = client.get("/api/v1/kb/healthz")
    assert health.status_code == 200
    assert health.json()["nodes"] == 1

    stats = client.get("/api/v1/kb/stats").json()
    assert stats["nodes"] == 1
    assert stats["by_kind"] == {"fact": 1}


def test_crud_roundtrip_and_conflict(client: TestClient) -> None:
    created = _create(client)
    node_id = str(created["id"])
    revision = str(created["revision"])

    detail = client.get(f"/api/v1/kb/nodes/{node_id}")
    assert detail.status_code == 200
    assert detail.json()["revision"] == revision

    conflict = client.put(
        f"/api/v1/kb/nodes/{node_id}",
        json={"expected_revision": "stale", "title": "改标题"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 1010

    updated = client.put(
        f"/api/v1/kb/nodes/{node_id}",
        json={"expected_revision": revision, "title": "改标题", "body": "新正文"},
    )
    assert updated.status_code == 200
    new_revision = str(updated.json()["revision"])
    assert new_revision != revision

    deleted = client.delete(f"/api/v1/kb/nodes/{node_id}", params={"revision": new_revision})
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/kb/nodes/{node_id}").status_code == 404

    trash = client.get("/api/v1/kb/trash").json()
    assert trash["total"] == 1
    restored = client.post("/api/v1/kb/trash/restore", json={"trash": trash["items"][0]["trash"]})
    assert restored.status_code == 200
    assert client.get(f"/api/v1/kb/nodes/{node_id}").status_code == 200


def test_edges_route_is_not_shadowed_by_greedy_node_id(client: TestClient) -> None:
    a = _create(client, slug="a")
    b = _create(client, title="B", slug="b")

    response = client.put(
        f"/api/v1/kb/nodes/{a['id']}/edges",
        json={"edges": [{"predicate": "related_to", "target": b["id"]}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["added"] == 1

    detail = client.get(f"/api/v1/kb/nodes/{a['id']}").json()
    assert [edge["target"] for edge in detail["edges"]["out"]] == [b["id"]]


def test_validation_errors_use_envelope(client: TestClient) -> None:
    bad = client.post("/api/v1/kb/nodes", json={"kind": "entity", "title": "服务缺 entity_kind"})
    assert bad.status_code == 422
    assert bad.json()["code"] == 1012

    missing = client.get("/api/v1/kb/nodes/memhub/fact/nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == 1011


def test_list_and_search(client: TestClient) -> None:
    _create(client, slug="proxy")
    _create(client, slug="window", kind="procedure", title="夜间窗口")

    listing = client.get("/api/v1/kb/nodes", params={"kind": "fact"}).json()
    assert listing["total"] == 1

    found = client.get("/api/v1/kb/search", params={"q": "代理", "tier": "all"}).json()
    assert [item["id"] for item in found["results"]] == ["memhub/fact/proxy"]


def test_audit_reports_orphans(client: TestClient) -> None:
    _create(client)
    issues = client.get("/api/v1/kb/audit").json()
    assert any(issue["type"] == "orphan" for issue in issues["issues"])


def test_spa_fallback_and_api_404(client: TestClient) -> None:
    page = client.get("/nodes/memhub")
    assert page.status_code == 200
    assert "memhub" in page.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    unknown = client.get("/api/v1/kb/unknown")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == 1011


def test_projection_status_reports_stale(client: TestClient) -> None:
    _create(client)
    status = client.get("/api/v1/kb/projection").json()
    assert status["stale"] is True
    assert status["graph"].endswith("kg.json")


def test_projection_status_counts_existing_graph(client: TestClient, tmp_path: Path) -> None:
    graph = tmp_path / "kb" / "kg.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text('{"nodes": [{}, {}], "edges": [{}]}', encoding="utf-8")

    status = client.get("/api/v1/kb/projection").json()
    assert status["nodes"] == 2
    assert status["edges"] == 1


def test_projects_and_scoped_graph(client: TestClient) -> None:
    created = _create(client)
    node_id = str(created["id"])

    projects = client.get("/api/v1/kb/projects").json()
    assert [item["id"] for item in projects["items"]] == ["memhub"]
    assert projects["items"][0]["nodes"] == 1

    made = client.post(
        "/api/v1/kb/projects",
        json={"id": "sdp-tag", "name": "SDP 标签", "description": "评测体系"},
    )
    assert made.status_code == 201
    assert made.json()["name"] == "SDP 标签"

    renamed = client.patch("/api/v1/kb/projects/sdp-tag", json={"description": "改过"})
    assert renamed.json()["description"] == "改过"

    graph = client.get("/api/v1/kb/graph", params={"project": "memhub"}).json()
    assert [node["id"] for node in graph["nodes"]] == [node_id]
    assert graph["edges"] == []

    empty = client.get("/api/v1/kb/graph", params={"project": "sdp-tag"}).json()
    assert empty["nodes"] == []

    missing = client.get("/api/v1/kb/graph", params={"project": "nope"})
    assert missing.status_code == 404
    assert missing.json()["code"] == 1011


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/api/v1/kb/nodes", json={"kind": "fact", "title": "x", "bogus": 1})
    assert response.status_code == 422
