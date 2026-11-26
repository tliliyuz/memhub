"""知识库管理 API 的契约行为（状态码、错误信封、路由顺序、SPA 回退）。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from memhub.kb.api import create_app
from memhub.kb.models import KbMemoryCandidate, KbMemoryEntry
from memhub.kb.session import KB_DSN_KEY
from memhub.kb.store import KnowledgeStore


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kb_pg_schema: str, test_dsn: str
) -> Iterator[TestClient]:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>memhub</title>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setenv(KB_DSN_KEY, test_dsn)
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(web))

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
    assert client.get("/api/v1/kb/healthz").json()["nodes"] == 1
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


def test_healthz_has_no_projection_state(client: TestClient) -> None:
    """投影子系统已下线：健康检查只报真源与规模。"""
    payload = client.get("/api/v1/kb/healthz").json()
    assert set(payload) == {"ok", "store", "nodes"}
    assert payload["store"] == "pg"


def test_projection_routes_are_removed(client: TestClient) -> None:
    """投影与重建接口不再存在。

    GET 未知 `/api` 路径由 SPA 回退返回 404/1011；POST 没有 SPA 路由，FastAPI
    按方法不匹配返回 405。两者都说明重建接口已不存在。
    """
    for method, path, status in (
        ("get", "/api/v1/kb/projection", 404),
        ("get", "/api/v1/kb/rebuild", 404),
        ("post", "/api/v1/kb/rebuild", 405),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == status, (method, path, response.text)
    assert client.get("/api/v1/kb/projection").json()["code"] == 1011


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


# -- 长期记忆（规格 §8） -----------------------------------------------------

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)


class _MemorySeeder:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def entry(self, slug: str, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "slug": slug,
            "title": "重试退避",
            "conclusion": "失败后的重试要带指数退避。",
            "boundary": "幂等操作",
            "invalidation": "",
            "evidence": [],
            "confidence": 0.8,
            "status": "active",
            "contradicts": [],
            "revision": f"{slug[:1] or '0'}" * 16,
            "created_at": NOW,
            "updated_at": NOW,
        }
        values.update(overrides)
        with Session(self.engine) as session:
            session.add(KbMemoryEntry(**values))
            session.commit()
        return values

    def candidate(self, slug: str, **overrides: Any) -> None:
        values: dict[str, Any] = {
            "slug": slug,
            "title": "迁移先备份",
            "conclusion": "改表前先备份。",
            "boundary": "",
            "invalidation": "",
            "evidence": [],
            "confidence": 0.5,
            "session_count": 1,
            "project_count": 1,
            "status": "pending",
            "reason": "below_threshold",
            "contradicts": [],
            "first_seen_at": NOW,
            "last_seen_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }
        values.update(overrides)
        with Session(self.engine) as session:
            session.add(KbMemoryCandidate(**values))
            session.commit()


@pytest.fixture
def memory_seed(test_dsn: str, kb_pg_schema: str) -> Iterator[_MemorySeeder]:
    url = test_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, connect_args={"options": f"-csearch_path={kb_pg_schema}"})
    try:
        yield _MemorySeeder(engine)
    finally:
        engine.dispose()


def test_memory_list_filters_and_detail(client: TestClient, memory_seed: _MemorySeeder) -> None:
    memory_seed.entry("retry-backoff", title="重试退避")
    memory_seed.entry(
        "old-rule",
        title="旧规则",
        conclusion="旧结论。",
        status="deprecated",
        deprecated_reason="过期",
    )

    listing = client.get("/api/v1/kb/memories", params={"status": "active"})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert set(body) == {"items", "total", "offset", "limit"}
    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == ["retry-backoff"]

    everything = client.get("/api/v1/kb/memories", params={"status": "all"}).json()
    assert everything["total"] == 2

    found = client.get("/api/v1/kb/memories", params={"q": "旧规则"}).json()
    assert [item["slug"] for item in found["items"]] == ["old-rule"]

    paginated = client.get(
        "/api/v1/kb/memories", params={"status": "all", "limit": 1, "offset": 1}
    ).json()
    assert paginated["limit"] == 1 and paginated["offset"] == 1
    assert len(paginated["items"]) == 1

    detail = client.get("/api/v1/kb/memories/retry-backoff")
    assert detail.status_code == 200
    assert detail.json()["slug"] == "retry-backoff"
    assert detail.json()["revisions"] == []

    missing = client.get("/api/v1/kb/memories/ghost")
    assert missing.status_code == 404
    assert missing.json()["code"] == 1011


def test_memory_patch_optimistic_lock_and_deprecate(
    client: TestClient, memory_seed: _MemorySeeder
) -> None:
    seeded = memory_seed.entry("retry-backoff")

    stale = client.patch(
        "/api/v1/kb/memories/retry-backoff",
        json={"expected_revision": "0" * 16, "conclusion": "过期修改。"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == 1010

    updated = client.patch(
        "/api/v1/kb/memories/retry-backoff",
        json={"expected_revision": seeded["revision"], "conclusion": "新的结论。"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["conclusion"] == "新的结论。"
    assert updated.json()["revision"] != seeded["revision"]

    deprecated = client.post(
        "/api/v1/kb/memories/retry-backoff/deprecate",
        json={"expected_revision": updated.json()["revision"], "reason": "被替代"},
    )
    assert deprecated.status_code == 200, deprecated.text
    assert deprecated.json()["status"] == "deprecated"
    assert deprecated.json()["deprecated_reason"] == "被替代"

    again = client.post(
        "/api/v1/kb/memories/retry-backoff/deprecate",
        json={"expected_revision": deprecated.json()["revision"], "reason": "重复废弃"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == 1010

    missing = client.patch(
        "/api/v1/kb/memories/ghost",
        json={"expected_revision": "0" * 16, "conclusion": "x"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == 1011


def test_memory_candidates_filter(client: TestClient, memory_seed: _MemorySeeder) -> None:
    memory_seed.candidate("below")
    memory_seed.candidate(
        "conflicted",
        status="conflict",
        reason="conclusion_differs",
        contradicts=["below"],
    )

    pending = client.get("/api/v1/kb/memories/candidates", params={"status": "pending"})
    assert pending.status_code == 200, pending.text
    assert [item["slug"] for item in pending.json()["items"]] == ["below"]

    everything = client.get("/api/v1/kb/memories/candidates", params={"status": "all"})
    assert everything.json()["total"] == 2
    conflict = next(item for item in everything.json()["items"] if item["slug"] == "conflicted")
    assert conflict["status"] == "conflict"
    assert conflict["contradicts"] == ["below"]


def test_memory_snapshot_publish_activate_disable(
    client: TestClient, memory_seed: _MemorySeeder
) -> None:
    memory_seed.entry("retry-backoff")

    first = client.post("/api/v1/kb/memories/snapshots", json={"note": "第一版"})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "published"
    assert first.json()["item_count"] == 1

    second = client.post("/api/v1/kb/memories/snapshots", json={})
    assert second.status_code == 200
    assert second.json()["version"] != first.json()["version"]

    listing = client.get("/api/v1/kb/memories/snapshots").json()
    assert listing["total"] == 2
    assert [item["version"] for item in listing["items"]] == [
        second.json()["version"],
        first.json()["version"],
    ]

    rollback = client.post(f"/api/v1/kb/memories/snapshots/{first.json()['version']}/activate")
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "published"

    disabled = client.post(
        f"/api/v1/kb/memories/snapshots/{first.json()['version']}/disable",
        json={"reason": "回滚验收"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    missing = client.post("/api/v1/kb/memories/snapshots/99999/activate")
    assert missing.status_code == 404
    assert missing.json()["code"] == 1011

    bad_version = client.post("/api/v1/kb/memories/snapshots/not-a-number/activate")
    assert bad_version.status_code == 422


def test_memory_routes_require_pg(tmp_path: Path) -> None:
    with TestClient(create_app(store=KnowledgeStore(tmp_path / "kb"))) as test_client:  # type: ignore[arg-type]
        for path in (
            "/api/v1/kb/memories",
            "/api/v1/kb/memories/candidates",
            "/api/v1/kb/memories/snapshots",
        ):
            response = test_client.get(path)
            assert response.status_code == 503, path
            assert response.json()["code"] == 2001
