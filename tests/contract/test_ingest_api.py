"""采集 API 契约：信封、鉴权、游标冲突、幂等。

采集目标只认 `kb_projects`（规格 §9.2.4）：`registered-only` 已归档，`dir-only`
与 `ghost` 没有行，都不得写入。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest
from fastapi.testclient import TestClient

from memhub.ingest.app import create_app
from memhub.kb.models import KbArchive
from memhub.kb.session import KbDsnMissing, create_runtime_store

DEVICE = str(uuid.uuid4())
TOKEN = "devtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

ACTIVE_PROJECTS = ("sdp-tag", "other-kb")
ARCHIVED_PROJECTS = ("registered-only",)


async def _seed_targets(dsn: str, schema: str) -> None:
    store = create_runtime_store(dsn=dsn, schema=schema)
    try:
        for project in ACTIVE_PROJECTS:
            await store.register_project(project)
        for project in ARCHIVED_PROJECTS:
            await store.register_project(project)
            await store.archive_project(project)
    finally:
        await store.aclose()


@pytest.fixture
def kb_targets(kb_pg_schema: str, test_dsn: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """登记采集目标并返回隔离 schema；应用用同一 schema 构造 PG 存储。"""
    monkeypatch.setenv("MEMHUB_KB_DB_URL", test_dsn)
    asyncio.run(_seed_targets(test_dsn, kb_pg_schema))
    return kb_pg_schema


def _archive_target(schema: str, project: str) -> None:
    """测试中途归档：模拟「已落盘批次的目标后来被归档」。"""

    async def run() -> None:
        store = create_runtime_store(schema=schema)
        try:
            await store.archive_project(project)
        finally:
            await store.aclose()

    asyncio.run(run())


def _open_pending_archive(schema: str) -> None:
    """留下未完成的归档事务：目标登记状态不可确认。"""

    async def run() -> None:
        store = create_runtime_store(schema=schema)
        try:
            async with store.sessions() as session:
                session.add(
                    KbArchive(
                        archive_id="p" * 32,
                        project="sdp-tag",
                        status="pending",
                        snapshot=b"",
                        archived_count=0,
                        removed_edges=0,
                        created_at=datetime.now(UTC),
                    )
                )
                await session.commit()
        finally:
            await store.aclose()

    asyncio.run(run())


@pytest.fixture
def client(kb_targets: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    with TestClient(create_app(schema=kb_targets)) as test_client:
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


def _assert_target_denied(status: int, body: dict[str, object], reason: str) -> None:
    assert status == 400
    assert body["code"] == 1003
    assert body["data"] == {"reason": reason}


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
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配置 DATA_DIR 后原始字节必须落盘。"""
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app(schema=kb_targets)) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        status, _ = _push(fresh, [_file("a.jsonl", "hello")])
        assert status == 200
    stored = list((tmp_path / "raw_store").rglob("*.json"))
    assert len(stored) == 1
    assert __import__("json").loads(stored[0].read_text(encoding="utf-8"))["content"] == "hello"


@pytest.mark.parametrize(
    ("project", "reason"),
    [
        ("ghost", "unregistered"),
        # 目录存在不再是判据：`kb_projects` 没有行就是未登记。
        ("dir-only", "unregistered"),
        ("registered-only", "inactive"),
    ],
)
def test_unavailable_project_never_reaches_quota_or_state(
    kb_targets: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project: str,
    reason: str,
) -> None:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    # 配额先于目标检查会让拒绝类型泄露，而且同一批修正目标后必须能正常提交。
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "1000")
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
            ),
            reason,
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
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, empty_first: bool
) -> None:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    first = [] if empty_first else [_file("a.jsonl", "hello")]
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
            ),
            "target_conflict",
        )
        # 同目标重放也不得把不同内容追加到已接受的批次。
        status, body = _push(
            fresh, [_file("b.jsonl", "replayed content")], batch_id="b1", project="sdp-tag"
        )
        assert status == 200 and body["data"]["replayed"] is True
        assert body["data"]["accepted"] == len(first)
    assert len(list((tmp_path / "raw_store").rglob("*.json"))) == len(first)


def test_archived_target_denies_existing_replay(
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app(schema=kb_targets)) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        files = [_file("a.jsonl", "hello")]
        assert _push(fresh, files, batch_id="b1")[0] == 200
        # 已落盘批次的目标后来被归档（`kb_projects.archived_at`）：重放也不能借旧记录继续写。
        _archive_target(kb_targets, "sdp-tag")
        _assert_target_denied(*_push(fresh, files, batch_id="b1"), "inactive")


def test_target_lookup_failure_is_generic(
    kb_targets: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app(schema=kb_targets)) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        # 未完成的归档事务让「已登记且活动」无法确认：只能给通用 500，不能泄露目标细节。
        _open_pending_archive(kb_targets)
        status, body = _push(fresh, [_file("a.jsonl", "hello")], project="sdp-tag")
        assert status == 500
        assert body["code"] == 2001
        assert body["data"] == {}
        assert "sdp-tag" not in body["message"]
        assert str(tmp_path) not in body["message"]
        assert not (tmp_path / "raw_store").exists()


def test_chosen_project_is_persisted_for_the_worker(
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """桌面端选的知识库要随批次落盘，worker 才能写进对应的 `kb_projects`。"""
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app(schema=kb_targets)) as fresh:
        fresh.post(
            "/devices/register",
            json={"device_id": DEVICE, "name": "test", "platform": "win32"},
        )
        status, _ = _push(fresh, [_file("a.jsonl", "hello")], project="sdp-tag")
        assert status == 200
    stored = list((tmp_path / "raw_store").rglob("*.json"))
    assert json.loads(stored[0].read_text(encoding="utf-8"))["project"] == "sdp-tag"


@pytest.mark.parametrize(
    ("project", "reason"),
    [
        (_MISSING, "missing"),
        (None, "missing"),
        ("", "missing"),
        ("auto", "reserved"),
        (" ", "invalid"),
        # 非字符串目标在校验器里先收敛为「没给出字符串 id」，不做类型回显。
        (123, "missing"),
        (["sdp-tag"], "missing"),
        ({"id": "sdp-tag"}, "missing"),
        ("../etc", "invalid"),
        ("Sdp-Tag", "invalid"),
        (" test-kb", "invalid"),
        ("test-kb ", "invalid"),
    ],
)
def test_invalid_project_is_rejected(client: TestClient, project: object, reason: str) -> None:
    """目标不合规统一报错，用 data.reason 区分；不回显客户端传来的项目值。"""
    _assert_target_denied(*_push(client, [_file("a.jsonl", "hello")], project=project), reason)


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
    """缺 DSN 直接启动失败：登记状态没有内存或文件退路（规格 §9.2.4）。"""
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    for key in ("MEMHUB_DATA_DIR", "MEMHUB_KB_DB_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(KbDsnMissing):
        create_app()


def test_prod_start_also_requires_kb_dsn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.delenv("MEMHUB_KB_DB_URL", raising=False)
    with pytest.raises(KbDsnMissing):
        create_app()


def test_ingest_decisions_are_audited_without_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """每次采集一条审计：设备、目标、接受/拒绝、理由；不含正文与 token。"""
    caplog.set_level(logging.INFO, logger="memhub.ingest.audit")
    _push(client, [_file("a.jsonl", "secret-body")], project="sdp-tag")
    _push(client, [_file("b.jsonl", "secret-body")], project="ghost")

    records = [record.getMessage() for record in caplog.records]
    accepted, rejected = records[0], records[1]
    assert "decision=accept" in accepted
    assert f"device={DEVICE!r}" in accepted
    assert "project='sdp-tag'" in accepted
    assert "decision=reject" in rejected and "reason=unregistered" in rejected
    assert "secret-body" not in accepted + rejected
    assert TOKEN not in accepted + rejected


def test_project_list_only_exposes_registered_active_projects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """保留 kb-api 的项目元数据和顺序，但只返回当前已登记且活动的目标。"""
    calls: list[tuple[str, str]] = []
    visible = [
        {"id": "sdp-tag", "name": "SDP Tag", "nodes": 3},
        {"id": "other-kb", "name": "Other KB", "nodes": 0},
    ]

    async def fake(base_url: str, method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        calls.append((method, path))
        return {
            "items": [
                {"id": "not-registered"},
                visible[0],
                {"id": "dir-only"},
                visible[1],
                {"id": "registered-only"},
            ],
            "total": 5,
        }

    monkeypatch.setattr("memhub.ingest.app._kb_api_request", fake)
    response = client.get(
        "/ingest/projects",
        params={"device_id": DEVICE, "limit": 1, "offset": 1},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"items": visible, "total": 2, "writable_only": True}
    assert calls == [("GET", "/api/v1/kb/projects")]


def test_project_create_route_is_removed(client: TestClient) -> None:
    """客户端只上传；建库只走管理台，采集端不再代理建库。"""
    response = client.post(
        "/ingest/projects",
        headers=AUTH,
        json={"device_id": DEVICE, "id": "new-kb", "name": "新库"},
    )
    assert response.status_code in {404, 405}


def test_project_list_requires_device_token(client: TestClient) -> None:
    response = client.get("/ingest/projects", params={"device_id": DEVICE})
    assert response.status_code == 401


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


def test_prod_ignores_dev_token(
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """prod 下共享 dev token 即便被误配也不生效（文档约定）。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", "shared-dev")
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    payload = {"device_id": DEVICE, "name": "test", "platform": "win32"}
    with TestClient(create_app(schema=kb_targets)) as fresh:
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


def test_prod_requires_device_id(
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 0.3：生产 device_id 必填，服务端自动生成只留给 dev stub。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    with TestClient(create_app(schema=kb_targets)) as fresh:
        response = fresh.post(
            "/devices/register",
            json={"name": "test", "platform": "win32"},
            headers={"Authorization": "Bearer prov-secret"},
        )
        assert response.status_code == 400


def test_per_device_token_is_issued_and_scoped(
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """生产 token 与设备绑定：签给别人设备的 token 用不了。"""
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """raw_store 满了返回 1008 而不是写满磁盘；被拒批次一个字节都不落。"""
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "600")
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
    kb_targets: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配额按新增字节算：重放已收下的批次仍成功，新内容才被拒。"""
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    monkeypatch.setenv("MEMHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "2000")
    with TestClient(create_app(schema=kb_targets)) as fresh:
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
