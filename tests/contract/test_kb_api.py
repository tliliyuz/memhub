"""知识库管理 API 的契约行为（状态码、错误信封、路由顺序、SPA 回退）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memhub.kb.api import create_app
from memhub.kb.session import KB_DSN_KEY


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kb_pg_schema: str, test_dsn: str
) -> Iterator[TestClient]:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>memhub</title>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setenv(KB_DSN_KEY, test_dsn)
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kb" / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(web))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.delenv("MEMHUB_KB_GRAPH_PORT", raising=False)

    with TestClient(create_app(schema=kb_pg_schema)) as test_client:
        yield test_client


def _ensure_project(client: TestClient, project: object) -> None:
    """存储层不再隐式建库：先通过管理接口显式建库（幂等）。"""
    listed = {item["id"] for item in client.get("/api/v1/kb/projects").json()["items"]}
    if project in listed:
        return
    response = client.post("/api/v1/kb/projects", json={"id": project})
    assert response.status_code == 201, response.text


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "fact",
        "title": "HTTPX trust_env 导致代理 502",
        "body": "先看 trust_env。",
        "project": "memhub",
        "tags": ["httpx"],
    }
    payload.update(overrides)
    _ensure_project(client, payload["project"])
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


def test_current_user_uses_gateway_identity(client: TestClient) -> None:
    local = client.get("/api/v1/kb/me")
    assert local.json() == {"authenticated": False, "user": None, "avatar_url": None}

    logged_in = client.get("/api/v1/kb/me", headers={"X-Memhub-User": "sample-user"})
    assert logged_in.status_code == 200
    assert logged_in.headers["Cache-Control"] == "no-store"
    assert logged_in.json() == {
        "authenticated": True,
        "user": "sample-user",
        "avatar_url": "https://github.com/sample-user.png?size=64",
    }


def test_archive_project_and_page_trash(client: TestClient) -> None:
    first = _create(client, project="old", slug="first")
    second = _create(client, project="old", slug="second")
    _create(client, project="keep")

    deleted = client.delete("/api/v1/kb/projects/old")
    assert deleted.status_code == 200
    assert deleted.json()["archived_count"] == 2
    assert client.delete("/api/v1/kb/projects/old").status_code == 404
    assert [item["id"] for item in client.get("/api/v1/kb/projects").json()["items"]] == ["keep"]

    archives = client.get("/api/v1/kb/trash/projects")
    assert archives.status_code == 200
    archive_id = deleted.json()["archive_id"]
    assert [item["archive_id"] for item in archives.json()["items"]] == [archive_id]
    assert client.get("/api/v1/kb/trash").json()["total"] == 0
    rebuilt = client.post("/api/v1/kb/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["nodes"] == 1
    assert rebuilt.json()["stale"] is False
    restored = client.post("/api/v1/kb/trash/projects/restore", json={"archive_id": archive_id})
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored_count"] == 2
    assert client.get("/api/v1/kb/trash/projects").json()["total"] == 0
    for node in (first, second):
        assert client.get(f"/api/v1/kb/nodes/{node['id']}").status_code == 200


def test_page_individual_trash(client: TestClient) -> None:
    first = _create(client, project="old", slug="first")
    second = _create(client, project="old", slug="second", title="Second")
    for node in (first, second):
        response = client.delete(
            f"/api/v1/kb/nodes/{node['id']}", params={"revision": node["revision"]}
        )
        assert response.status_code == 200
    page = client.get("/api/v1/kb/trash", params={"project": "old", "limit": 1, "offset": 1})
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["total_all"] == 2
    assert page.json()["offset"] == 1
    assert [item["id"] for item in page.json()["items"]] == [first["id"]]
    filtered = client.get("/api/v1/kb/trash", params={"q": "second"}).json()
    assert filtered["total"] == 1
    assert filtered["total_all"] == 2
    assert [item["id"] for item in filtered["items"]] == [second["id"]]


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
    _ensure_project(client, "memhub")
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

    # 重复创建是冲突（1010），客户端据此提示「已存在，可直接选用」；
    # 1012 只表示 id 不合法，两者的 UI 处理不同。
    duplicate = client.post("/api/v1/kb/projects", json={"id": "sdp-tag"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 1010

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
