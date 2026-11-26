"""ADR-0014 管理台写入层级验收（规格 docs/plans/tier-canonical-spec.md §4.1）。

管理台新建/更新不得再写 `candidate`：缺省即 `canonical`，显式传 `candidate`
返回 `422/1012`。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.contract.test_kb_api import _create, _ensure_project

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
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(web))

    with TestClient(create_app(schema=kb_pg_schema)) as test_client:
        yield test_client


def test_create_defaults_to_canonical(client: TestClient) -> None:
    created = _create(client)
    node_id = str(created["id"])
    detail = client.get(f"/api/v1/kb/nodes/{node_id}").json()
    assert detail["frontmatter"]["tier"] == "canonical"


def test_create_rejects_candidate_tier(client: TestClient) -> None:
    response = client.post(
        "/api/v1/kb/nodes",
        json={
            "kind": "fact",
            "title": "显式候选",
            "body": "先看 trust_env。",
            "project": "memhub",
            "tier": "candidate",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == 1012


def test_update_rejects_candidate_tier(client: TestClient) -> None:
    created = _create(client)
    node_id = str(created["id"])
    revision = str(created["revision"])
    response = client.put(
        f"/api/v1/kb/nodes/{node_id}",
        json={"expected_revision": revision, "tier": "candidate"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 1012
    detail = client.get(f"/api/v1/kb/nodes/{node_id}").json()
    assert detail["frontmatter"]["tier"] == "canonical"


def test_update_accepts_canonical_tier(client: TestClient) -> None:
    created = _create(client)
    node_id = str(created["id"])
    revision = str(created["revision"])
    response = client.put(
        f"/api/v1/kb/nodes/{node_id}",
        json={"expected_revision": revision, "tier": "canonical"},
    )
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/v1/kb/nodes/{node_id}").json()
    assert detail["frontmatter"]["tier"] == "canonical"


def test_search_rejects_candidate_tier(client: TestClient) -> None:
    _ensure_project(client, "memhub")
    response = client.get("/api/v1/kb/search", params={"q": "任意", "tier": "candidate"})
    assert response.status_code == 422
