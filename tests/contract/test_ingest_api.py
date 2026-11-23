"""采集 API 契约：信封、鉴权、游标冲突、幂等。"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest
from fastapi.testclient import TestClient

from memhub.ingest.app import create_app

DEVICE = str(uuid.uuid4())
TOKEN = "devtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _configure_targets(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    knowledge = root / "knowledge"
    grants = root / "config" / "ingest-grants.json"
    for project in ("sdp-tag", "other-kb", "dir-only", "not-granted"):
        (knowledge / project).mkdir(parents=True)
    registry = knowledge / ".kbs.json"
    registry.write_text(
        json.dumps(
            {
                "kbs": [
                    {"id": project}
                    for project in ("sdp-tag", "other-kb", "not-granted", "registered-only")
                ]
            }
        ),
        encoding="utf-8",
    )
    grants.parent.mkdir()
    grants.write_text(
        json.dumps(
            {
                "devices": {
                    DEVICE: [
                        "sdp-tag",
                        "other-kb",
                        "dir-only",
                        "registered-only",
                        "new-kb",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    monkeypatch.setenv("MEMHUB_INGEST_GRANTS_PATH", str(grants))
    return registry, grants


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
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


_MISSING = object()


def _push(
    client: TestClient,
    files: list[dict[str, object]],
    *,
    source_rev: int = 0,
    batch_id: str | None = None,
    project: object = "sdp-tag",
    device_id: str = DEVICE,
    headers: dict[str, str] | None = AUTH,
) -> tuple[int, dict[str, object]]:
    payload = {
        "batch_id": batch_id or str(uuid.uuid4()),
        "device_id": device_id,
        "source_id": "cc-sessions",
        "source_type": "sessions",
        "source_rev": source_rev,
        "files": files,
    }
    if project is not _MISSING:
        payload["project"] = project
    response = client.post("/ingest/raw", headers=headers, json=payload)
    return response.status_code, response.json()


def _assert_target_denied(status: int, body: dict[str, object]) -> None:
    assert status == 400
    assert body["code"] == 1003
    assert body["data"] == {"reason": "target_unavailable"}


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


def test_register_is_idempotent_for_same_device(client: TestClient) -> None:
    """契约 0.3：未吊销时重复注册返回同一枚 token，provision 重试安全。"""
    payload = {"device_id": DEVICE, "name": "test", "platform": "win32"}
    first = client.post("/devices/register", json=payload).json()
    second = client.post("/devices/register", json=payload).json()
    assert first["code"] == second["code"] == 0
    assert first["data"]["device_id"] == second["data"]["device_id"] == DEVICE
    assert first["data"]["device_token"] == second["data"]["device_token"]


def test_raw_bytes_are_persisted_when_data_dir_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """未配置授权文件路径时使用 DATA_DIR 的默认路径，原始字节必须落盘。"""
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.delenv("MEMHUB_INGEST_GRANTS_PATH")
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        status, _ = _push(fresh, [_file("a.jsonl", "hello")])
        assert status == 200
    stored = list((tmp_path / "raw_store").rglob("*.json"))
    assert len(stored) == 1
    assert __import__("json").loads(stored[0].read_text(encoding="utf-8"))["content"] == "hello"


@pytest.mark.parametrize("project", ["ghost", "dir-only", "registered-only", "not-granted"])
def test_unavailable_project_never_reaches_quota_or_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project: str,
) -> None:
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    # 配额先于目标检查会让拒绝类型泄露，而且同一批修正目标后必须能正常提交。
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "1000")
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        _assert_target_denied(
            *_push(
                fresh,
                [_file("a.jsonl", "x" * 2000)],
                batch_id="b1",
                project=project,
            )
        )
        assert not (tmp_path / "raw_store").exists()
        cursor = fresh.get(
            "/ingest/cursor",
            params={"device_id": DEVICE, "source_id": "cc-sessions"},
            headers=AUTH,
        )
        assert cursor.json()["data"]["files"] == []
        status, body = _push(fresh, [_file("a.jsonl", "hello")], batch_id="b1", project="sdp-tag")
        assert status == 200 and body["data"]["replayed"] is False


@pytest.mark.parametrize("empty_first", [False, True])
def test_replay_cannot_change_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    empty_first: bool,
) -> None:
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    first = [] if empty_first else [_file("a.jsonl", "hello")]
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        assert _push(fresh, first, batch_id="b1", project="sdp-tag")[0] == 200
        _assert_target_denied(
            *_push(
                fresh,
                [_file("b.jsonl", "other content")],
                batch_id="b1",
                project="other-kb",
            )
        )
        # 同目标重放也不得把不同内容追加到已接受的批次。
        status, body = _push(
            fresh, [_file("b.jsonl", "replayed content")], batch_id="b1", project="sdp-tag"
        )
        assert status == 200 and body["data"]["replayed"] is True
        assert body["data"]["accepted"] == len(first)
    assert len(list((tmp_path / "raw_store").rglob("*.json"))) == len(first)


def test_revoking_grant_denies_existing_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, grants = _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        files = [_file("a.jsonl", "hello")]
        assert _push(fresh, files, batch_id="b1")[0] == 200
        grants.write_text(json.dumps({"devices": {DEVICE: []}}), encoding="utf-8")
        _assert_target_denied(*_push(fresh, files, batch_id="b1"))


@pytest.mark.parametrize("broken_path", ["registry", "grants"])
def test_target_lookup_failure_is_generic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    broken_path: str,
) -> None:
    registry, grants = _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        (registry if broken_path == "registry" else grants).write_text("invalid", encoding="utf-8")
        status, body = _push(fresh, [_file("a.jsonl", "hello")], project="sdp-tag")
        assert status == 500
        assert body["code"] == 2001
        assert body["data"] == {}
        assert "sdp-tag" not in body["message"]
        assert str(tmp_path) not in body["message"]
        assert not (tmp_path / "raw_store").exists()


def test_chosen_project_is_persisted_for_the_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """桌面端按目录选的知识库要随批次落盘，worker 才能写进对应 markdown 目录。"""
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        status, _ = _push(fresh, [_file("a.jsonl", "hello")], project="sdp-tag")
        assert status == 200
    stored = list((tmp_path / "raw_store").rglob("*.json"))
    assert json.loads(stored[0].read_text(encoding="utf-8"))["project"] == "sdp-tag"


@pytest.mark.parametrize(
    "project",
    [_MISSING, None, "auto", "", " ", 123, ["sdp-tag"], {"id": "sdp-tag"}, "../etc", "Sdp-Tag"],
)
def test_invalid_project_is_rejected(client: TestClient, project: object) -> None:
    """目标不合规统一报错，不回显客户端传来的项目值。"""
    _assert_target_denied(*_push(client, [_file("a.jsonl", "hello")], project=project))


def test_target_validation_follows_device_auth(client: TestClient) -> None:
    status, body = _push(client, [], project={"id": "sdp-tag"}, headers=None)
    assert (status, body["code"]) == (401, 1001)
    status, body = _push(client, [], project=None, device_id="unregistered-device")
    assert (status, body["code"]) == (403, 1002)


def test_reserved_collector_device_is_denied(client: TestClient) -> None:
    """即使 dev 的设备状态里出现这个身份，也不能用它冒充管理台生产者。"""
    assert client.portal is not None
    client.portal.call(client.app.state.store.register_device, "kb-console")
    status, body = _push(client, [], project="sdp-tag", device_id="kb-console")
    assert (status, body["code"]) == (403, 1009)


def test_unconfigured_ingest_target_is_default_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    for key in ("MEMHUB_DATA_DIR", "MEMHUB_KNOWLEDGE_DIR", "MEMHUB_INGEST_GRANTS_PATH"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app()) as fresh:
        assert (
            fresh.post(
                "/devices/register",
                json={"device_id": DEVICE, "name": "test", "platform": "win32"},
            ).status_code
            == 200
        )
        _assert_target_denied(*_push(fresh, [], project="sdp-tag"))


def test_project_list_only_exposes_granted_active_projects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """保留 kb-api 的项目元数据和顺序，但只返回本设备可写的目标。"""
    calls: list[tuple[str, str]] = []
    visible = {"id": "sdp-tag", "name": "SDP Tag", "nodes": 3}

    async def fake(base_url: str, method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        calls.append((method, path))
        return {
            "items": [
                {"id": "not-granted"},
                visible,
                {"id": "dir-only"},
                {"id": "registered-only"},
            ],
            "total": 4,
        }

    monkeypatch.setattr("memhub.ingest.app._kb_api_request", fake)
    response = client.get(
        "/ingest/projects",
        params={"device_id": DEVICE, "limit": 1, "offset": 1},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"items": [visible], "total": 1, "writable_only": True}
    assert calls == [("GET", "/api/v1/kb/projects")]


def test_project_create_requires_pregrant(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake(base_url: str, method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        calls.append(method)
        return {"id": "unknown-project"}

    monkeypatch.setattr("memhub.ingest.app._kb_api_request", fake)
    response = client.post(
        "/ingest/projects",
        headers=AUTH,
        json={"device_id": DEVICE, "id": "unknown-project"},
    )
    _assert_target_denied(response.status_code, response.json())
    assert calls == []


def test_project_list_requires_device_token(client: TestClient) -> None:
    response = client.get("/ingest/projects", params={"device_id": DEVICE})
    assert response.status_code == 401


def test_project_create_is_validated_and_proxied(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, object] | None] = []

    async def fake(base_url: str, method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        seen.append(payload)
        return {"id": "new-kb", "name": "新库"}

    monkeypatch.setattr("memhub.ingest.app._kb_api_request", fake)
    response = client.post(
        "/ingest/projects",
        headers=AUTH,
        json={"device_id": DEVICE, "id": "new-kb", "name": "新库"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["id"] == "new-kb"
    assert seen == [{"id": "new-kb", "name": "新库", "description": ""}]


def test_project_create_rejects_reserved_auto(client: TestClient) -> None:
    response = client.post(
        "/ingest/projects",
        headers=AUTH,
        json={"device_id": DEVICE, "id": "auto"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1003
    assert body["data"]["reason"] == "reserved"


def test_project_create_rejects_bad_id(client: TestClient) -> None:
    response = client.post(
        "/ingest/projects",
        headers=AUTH,
        json={"device_id": DEVICE, "id": "New KB/../x"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1003
    assert body["data"]["reason"] == "invalid"


class _FakeKbResponse:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body, ensure_ascii=False)

    def json(self) -> dict[str, object]:
        return self._body


def _fake_http(response: _FakeKbResponse):  # type: ignore[no-untyped-def]
    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> bool:
            return False

        async def request(self, *_: object, **__: object) -> _FakeKbResponse:
            return response

    return FakeClient


def test_project_errors_keep_kb_business_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kb-api 的 1010（已存在）/1012（非法）要透传，桌面端才能分开提示。"""
    monkeypatch.setattr(
        "memhub.ingest.app.httpx.AsyncClient",
        _fake_http(_FakeKbResponse(409, {"code": 1010, "message": "知识库已存在"})),
    )
    response = client.post(
        "/ingest/projects", headers=AUTH, json={"device_id": DEVICE, "id": "sdp-tag"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == 1010
    assert response.json()["message"] == "知识库已存在"


def test_kb_api_outage_is_internal_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kb 容器没起来时返回 2001/500，桌面端据此退回手填 id。"""
    monkeypatch.setattr(
        "memhub.ingest.app.httpx.AsyncClient",
        _fake_http(_FakeKbResponse(502, {"message": "bad gateway"})),
    )
    response = client.get("/ingest/projects", params={"device_id": DEVICE}, headers=AUTH)
    assert response.status_code == 500
    assert response.json()["code"] == 2001


def test_prod_requires_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产缺 DATA_DIR 时拒绝启动，不静默丢原始增量。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_DATA_DIR"):
        create_app()


def test_prod_requires_device_token_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEMHUB_DEVICE_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_DEVICE_TOKEN_SECRET"):
        create_app()


def test_prod_ignores_dev_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """prod 下共享 dev token 即便被误配也不生效（文档约定）。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", "shared-dev")
    with TestClient(create_app()) as fresh:
        token = fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
            headers={"Authorization": "Bearer prov-secret"},
        ).json()["data"]["device_token"]
        assert token != "shared-dev"
        denied = fresh.get(
            "/ingest/cursor",
            params={"device_id": DEVICE, "source_id": "cc-sessions"},
            headers={"Authorization": "Bearer shared-dev"},
        )
        assert denied.status_code == 401


def test_prod_requires_provision_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """生产缺 provision token 拒绝启动——否则注册端点等于开放自助领 token。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("MEMHUB_PROVISION_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_PROVISION_TOKEN"):
        create_app()


def test_register_requires_provision_token_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    payload = {"device_id": DEVICE, "name": "test", "platform": "win32"}
    with TestClient(create_app()) as fresh:
        assert fresh.post("/devices/register", json=payload).status_code == 401
        wrong = fresh.post(
            "/devices/register", json=payload, headers={"Authorization": "Bearer nope"}
        )
        assert wrong.status_code == 401
        ok = fresh.post(
            "/devices/register",
            json=payload,
            headers={"Authorization": "Bearer prov-secret"},
        )
        assert ok.status_code == 200
        assert ok.json()["data"]["device_token"].startswith("v1.")


def test_prod_requires_device_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """契约 0.3：生产 device_id 必填，服务端自动生成只留给 dev stub。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    with TestClient(create_app()) as fresh:
        response = fresh.post(
            "/devices/register",
            json={"name": "test", "platform": "win32"},
            headers={"Authorization": "Bearer prov-secret"},
        )
        assert response.status_code == 400


def test_per_device_token_is_issued_and_scoped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """生产 token 与设备绑定：签给别人设备的 token 用不了。"""
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as fresh:
        registered = fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        ).json()
        token = registered["data"]["device_token"]
        assert token.startswith("v1.")

        response = fresh.get(
            "/ingest/cursor",
            params={"device_id": DEVICE, "source_id": "cc-sessions"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        # 同一枚 token 冒充另一个设备
        fresh.post(
            "/devices/register",
            json={"device_id": str(uuid.uuid4()), "name": "other", "platform": "win32"},
        )
        forged = fresh.get(
            "/ingest/cursor",
            params={"device_id": str(uuid.uuid4()), "source_id": "cc-sessions"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert forged.status_code == 401

        # 篡改签名的 token
        tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
        bad = fresh.get(
            "/ingest/cursor",
            params={"device_id": DEVICE, "source_id": "cc-sessions"},
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert bad.status_code == 401


def test_raw_store_quota_returns_1008_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """raw_store 满了返回 1008 而不是写满磁盘；被拒批次一个字节都不落。"""
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "600")
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        status, body = _push(fresh, [_file("a.jsonl", "x" * 1000)])
        assert status == 503
        assert body["code"] == 1008
        assert body["data"]["limit_bytes"] == 600
        assert list((tmp_path / "raw_store").rglob("*.json")) == []


def test_quota_rejects_only_new_content_not_replays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配额按新增字节算：重放已收下的批次仍成功，新内容才被拒。"""
    _configure_targets(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "2000")
    with TestClient(create_app()) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        first = _file("a.jsonl", "small")
        status, _ = _push(fresh, [first], batch_id="b-1")
        assert status == 200

        big = _file("b.jsonl", "y" * 3000)
        status, body = _push(fresh, [big])
        assert status == 503
        assert body["code"] == 1008

        # 已接收批次重放不执行配额检查；否则客户端重试会被永久卡死。
        status, body = _push(fresh, [first], batch_id="b-1")
        assert status == 200
        assert body["code"] == 0


def test_invalid_queue_max_bytes_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "not-a-number")
    with pytest.raises(RuntimeError, match="MEMHUB_QUEUE_MAX_BYTES"):
        create_app()
