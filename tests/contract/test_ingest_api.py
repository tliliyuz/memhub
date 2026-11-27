"""采集 API 契约：信封、鉴权、游标冲突、幂等、配额、清理与内部上传接口。

采集目标只认 `kb_projects`（规格 §9.2.4）：`registered-only` 已归档，`dir-only`
与 `ghost` 没有行，都不得写入。队列与正文可注入内存实现，契约测试不碰本机文件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self, cast

import pytest
from fastapi.testclient import TestClient

from memhub.ingest.app import create_app
from memhub.ingest.store import MemoryStore
from memhub.kb.errors import TargetUnavailable
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KbDsnMissing
from memhub.queue.content import LocalContentStore
from memhub.queue.identity import CONSOLE_DEVICE
from memhub.queue.tasks import MemoryQueue

DEVICE = str(uuid.uuid4())
TOKEN = "devtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
INTERNAL = "internal-secret"
INTERNAL_AUTH = {"Authorization": f"Bearer {INTERNAL}"}

ACTIVE_PROJECTS = ("sdp-tag", "other-kb")
ARCHIVED_PROJECTS = ("registered-only",)


class _Targets:
    """`kb_projects` 的替身：回答目标状态并收集写审计。"""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.audits: list[dict[str, Any]] = []
        self.registry_down = False
        self.pending_archive = False

    async def project_status(self, project: str) -> str:
        if self.registry_down or self.pending_archive:
            raise TargetUnavailable("registry_unavailable")
        return self.statuses.get(project, "unregistered")

    async def record_write_audit(self, **kwargs: Any) -> None:
        self.audits.append(kwargs)


@dataclass
class Harness:
    state: MemoryStore
    queue: MemoryQueue
    content: LocalContentStore
    targets: _Targets
    audits: list[dict[str, Any]] = field(default_factory=list)


def _targets() -> _Targets:
    statuses = {project: "active" for project in ACTIVE_PROJECTS}
    statuses.update({project: "inactive" for project in ARCHIVED_PROJECTS})
    return _Targets(statuses)


@pytest.fixture
def h(tmp_path: Any) -> Harness:
    return Harness(
        state=MemoryStore(),
        queue=MemoryQueue(),
        content=LocalContentStore(tmp_path / "content"),
        targets=_targets(),
    )


def _app(harness: Harness) -> Any:
    return create_app(
        harness.state,
        queue=harness.queue,
        content=harness.content,
        kb_store=cast(PgKnowledgeStore, harness.targets),
    )


@contextmanager
def _serve(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    register: bool = True,
    **env: str,
) -> Iterator[TestClient]:
    for key in ("MEMHUB_ENV", "MEMHUB_DATA_DIR", "MEMHUB_CH_URL", "MEMHUB_DB_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", TOKEN)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with TestClient(_app(harness)) as client:
        if register:
            provision = env.get("MEMHUB_PROVISION_TOKEN")
            response = client.post(
                "/devices/register",
                json={"device_id": DEVICE, "name": "test", "platform": "win32"},
                headers={"Authorization": f"Bearer {provision}"} if provision else {},
            )
            assert response.status_code == 200
        yield client


@pytest.fixture
def client(h: Harness, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with _serve(h, monkeypatch) as test_client:
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


def test_push_advances_cursor_and_queues_content(client: TestClient, h: Harness) -> None:
    status, body = _push(client, [_file("a.jsonl", "hello")])
    assert status == 200
    assert body["data"]["accepted"] == 1
    [row] = h.queue.rows.values()
    assert (row.project, row.status, row.size) == ("sdp-tag", "queued", 5)
    sha = row.sha256
    assert asyncio.run(h.content.get("sdp-tag", sha)) == "hello"

    response = client.get(
        "/ingest/cursor",
        params={"device_id": DEVICE, "source_id": "cc-sessions"},
        headers=AUTH,
    )
    files = response.json()["data"]["files"]
    assert files[0]["path"] == "a.jsonl"
    assert files[0]["offset"] == 5


def test_replayed_batch_returns_previous_result(client: TestClient, h: Harness) -> None:
    batch_id = str(uuid.uuid4())
    first = _push(client, [_file("a.jsonl", "hello")], batch_id=batch_id)
    second = _push(client, [_file("a.jsonl", "hello")], batch_id=batch_id)
    assert first[1]["data"]["replayed"] is False
    assert second[1]["data"]["replayed"] is True
    assert second[1]["data"]["accepted"] == first[1]["data"]["accepted"]
    assert len(h.queue.rows) == 1


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


def test_binary_content_is_rejected(client: TestClient, h: Harness) -> None:
    status, body = _push(client, [_file("a.bin", "abc\x00def")])
    assert status == 422
    assert body["code"] == 1006
    assert h.queue.rows == {}


def test_register_is_idempotent_for_same_device(client: TestClient) -> None:
    """契约 0.3：未吊销时重复注册返回同一枚 token，provision 重试安全。"""
    payload = {"device_id": DEVICE, "name": "test", "platform": "win32"}
    first = client.post("/devices/register", json=payload).json()
    second = client.post("/devices/register", json=payload).json()
    assert first["code"] == second["code"] == 0
    assert first["data"]["device_id"] == second["data"]["device_id"] == DEVICE
    assert first["data"]["device_token"] == second["data"]["device_token"]


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
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    reason: str,
) -> None:
    # 配额先于目标检查会让拒绝类型泄露，而且同一批修正目标后必须能正常提交。
    with _serve(h, monkeypatch, MEMHUB_QUEUE_MAX_BYTES="1000") as fresh:
        _assert_target_denied(
            *_push(fresh, [_file("a.jsonl", "x" * 2000)], batch_id="b1", project=project),
            reason,
        )
        assert h.queue.rows == {}
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
    h: Harness, monkeypatch: pytest.MonkeyPatch, empty_first: bool
) -> None:
    first = [] if empty_first else [_file("a.jsonl", "hello")]
    with _serve(h, monkeypatch) as fresh:
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
    assert len(h.queue.rows) == len(first)


def test_archived_target_denies_existing_replay(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch) as fresh:
        files = [_file("a.jsonl", "hello")]
        assert _push(fresh, files, batch_id="b1")[0] == 200
        # 已落盘批次的目标后来被归档（`kb_projects.archived_at`）：重放也不能借旧记录继续写。
        h.targets.statuses["sdp-tag"] = "inactive"
        _assert_target_denied(*_push(fresh, files, batch_id="b1"), "inactive")


def test_target_lookup_failure_is_generic(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    with _serve(h, monkeypatch) as fresh:
        # 未完成的归档事务让「已登记且活动」无法确认：只能给通用 500，不能泄露目标细节。
        h.targets.registry_down = True
        status, body = _push(fresh, [_file("a.jsonl", "hello")], project="sdp-tag")
        assert status == 500
        assert body["code"] == 2001
        assert body["data"] == {}
        assert "sdp-tag" not in body["message"]
        assert h.queue.rows == {}


def test_chosen_project_is_persisted_for_the_worker(client: TestClient, h: Harness) -> None:
    """桌面端选的知识库要随批次落盘，worker 才能写进对应的 `kb_projects`。"""
    status, _ = _push(client, [_file("a.jsonl", "hello")], project="sdp-tag")
    assert status == 200
    [row] = h.queue.rows.values()
    assert row.project == "sdp-tag"
    assert asyncio.run(h.content.get("sdp-tag", row.sha256)) == "hello"


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
    for key in ("MEMHUB_DATA_DIR", "MEMHUB_KB_RT_DB_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(KbDsnMissing):
        create_app()


def test_prod_start_requires_queue_and_content_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.delenv("MEMHUB_DB_URL", raising=False)
    monkeypatch.setenv("MEMHUB_CH_URL", "http://ch.invalid:8123")
    with pytest.raises(RuntimeError, match="MEMHUB_DB_URL"):
        create_app()

    monkeypatch.setenv("MEMHUB_DB_URL", "postgresql://u@127.0.0.1/memhub")
    monkeypatch.delenv("MEMHUB_CH_URL", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_CH_URL"):
        create_app()


def test_ingest_decisions_are_audited_without_content(
    client: TestClient, caplog: pytest.LogCaptureFixture, h: Harness
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


def test_ingest_decisions_are_recorded_in_write_audit(client: TestClient, h: Harness) -> None:
    """采集写审计：设备、目标、结果；不含正文与 token。"""
    _push(client, [_file("a2.jsonl", "secret-body")], project="sdp-tag")
    _push(client, [_file("b2.jsonl", "secret-body")], project="ghost")

    rows = [
        (row["actor"], row["project"], row["node_id"], row["action"], row["result"])
        for row in h.targets.audits
    ]
    assert rows == [
        (f"device:{DEVICE}", "sdp-tag", None, "ingest", "ok"),
        (f"device:{DEVICE}", "ghost", None, "ingest", "unregistered"),
    ]
    joined = repr(rows)
    assert "secret-body" not in joined
    assert TOKEN not in joined


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


_PROD_ENV = {
    "MEMHUB_ENV": "prod",
    "MEMHUB_DEVICE_TOKEN_SECRET": "test-secret",
    "MEMHUB_PROVISION_TOKEN": "prov-secret",
    "MEMHUB_DB_URL": "postgresql://u@127.0.0.1/memhub",
    "MEMHUB_CH_URL": "http://127.0.0.1:8123",
}


def test_prod_requires_device_token_secret(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.delenv("MEMHUB_DEVICE_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_DEVICE_TOKEN_SECRET"):
        _app(h)


def test_prod_ignores_dev_token(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """prod 下共享 dev token 即便被误配也不生效（文档约定）。"""
    env = {**_PROD_ENV, "MEMHUB_DEV_TOKEN": "shared-dev"}
    with _serve(h, monkeypatch, register=False, **env) as fresh:
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


def test_prod_requires_provision_token(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """生产缺 provision token 拒绝启动——否则注册端点等于开放自助领 token。"""
    monkeypatch.setenv("MEMHUB_ENV", "prod")
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("MEMHUB_PROVISION_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="MEMHUB_PROVISION_TOKEN"):
        _app(h)


def test_register_requires_provision_token_when_set(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("MEMHUB_PROVISION_TOKEN", "prov-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    payload = {"device_id": DEVICE, "name": "test", "platform": "win32"}
    with TestClient(_app(h)) as fresh:
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


def test_prod_requires_device_id(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约 0.3：生产 device_id 必填，服务端自动生成只留给 dev stub。"""
    with _serve(h, monkeypatch, register=False, **_PROD_ENV) as fresh:
        response = fresh.post(
            "/devices/register",
            json={"name": "test", "platform": "win32"},
            headers={"Authorization": "Bearer prov-secret"},
        )
        assert response.status_code == 400


def test_per_device_token_is_issued_and_scoped(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """生产 token 与设备绑定：签给别人设备的 token 用不了。"""
    monkeypatch.setenv("MEMHUB_DEVICE_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("MEMHUB_DEV_TOKEN", raising=False)
    with TestClient(_app(h)) as fresh:
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


def test_queue_quota_returns_1008_before_writing(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """队列满了返回 1008；被拒批次一个字节都不落，队列也不多一行。"""
    with _serve(h, monkeypatch, MEMHUB_QUEUE_MAX_BYTES="600") as fresh:
        status, body = _push(fresh, [_file("a.jsonl", "x" * 1000)])
        assert status == 503
        assert body["code"] == 1008
        assert body["data"]["limit_bytes"] == 600
        assert h.queue.rows == {}
        assert not h.content.root.exists()


def test_quota_rejects_only_new_content_not_replays(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配额按新增字节算：重放已收下的批次仍成功，新内容才被拒。"""
    with _serve(h, monkeypatch, MEMHUB_QUEUE_MAX_BYTES="2000") as fresh:
        first = _file("a.jsonl", "small")
        status, _ = _push(fresh, [first], batch_id="b-1")
        assert status == 200

        big = _file("b.jsonl", "y" * 3000)
        status, body = _push(fresh, [big])
        assert status == 503
        assert body["code"] == 1008
        assert len(h.queue.rows) == 1

        # 已接收批次重放不执行配额检查；否则客户端重试会被永久卡死。
        status, body = _push(fresh, [first], batch_id="b-1")
        assert status == 200
        assert body["code"] == 0


def test_invalid_queue_max_bytes_fails_startup(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_QUEUE_MAX_BYTES", "not-a-number")
    with pytest.raises(RuntimeError, match="MEMHUB_QUEUE_MAX_BYTES"):
        _app(h)


PROVISION = "prov-secret"
PROVISION_AUTH = {"Authorization": f"Bearer {PROVISION}"}


@contextmanager
def _provisioned(h: Harness, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """带 provision token 的应用；设备 token 走 dev token。"""
    with _serve(h, monkeypatch, MEMHUB_PROVISION_TOKEN=PROVISION) as client:
        yield client


def _purge(
    client: TestClient,
    source_id: str = "cc-sessions",
    *,
    device_id: str | None = DEVICE,
    headers: dict[str, str] | None = PROVISION_AUTH,
    purge: str | None = "true",
) -> tuple[int, dict[str, object]]:
    params = {}
    if device_id is not None:
        params["device_id"] = device_id
    if purge is not None:
        params["purge"] = purge
    response = client.delete(f"/ingest/source/{source_id}", params=params, headers=headers or {})
    return response.status_code, response.json()


async def _drain(h: Harness, *, processed: int = 0, reviewed: int = 0) -> None:
    for _ in range(processed):
        [task] = await h.queue.claim(limit=1)
        await h.queue.complete(task)
    for _ in range(reviewed):
        [task] = await h.queue.claim(limit=1)
        await h.queue.review(task, "boom")


@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer nope"}, AUTH])
def test_purge_rejects_missing_wrong_and_device_token(
    h: Harness, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str] | None
) -> None:
    """设备 token 与错误 token 都不能清理；采集器不得删自己的数据。"""
    with _provisioned(h, monkeypatch) as client:
        _push(client, [_file("a.jsonl", "hello")])
        status, body = _purge(client, headers=headers)
        assert status == 401
        assert body["code"] == 1001
        assert len(h.queue.rows) == 1


def test_purge_without_configured_provision_token_is_denied(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev stub 没配 provision token 时也不放开删除。"""
    with _serve(h, monkeypatch) as client:
        status, body = _purge(client, headers=AUTH)
        assert status == 401
        assert body["code"] == 1001
        status, _ = _purge(client, headers={"Authorization": "Bearer "})
        assert status == 401


def test_purge_removes_only_the_requested_source(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只删该 (device, source) 的队列行，别的源与别的设备不动。"""
    other_device = str(uuid.uuid4())
    with _provisioned(h, monkeypatch) as client:
        _push(client, [_file("a.jsonl", "hello")])
        _push(client, [_file("b.jsonl", "other")])
        registered = client.post(
            "/devices/register",
            json={"device_id": other_device, "name": "other", "platform": "win32"},
            headers=PROVISION_AUTH,
        )
        assert registered.status_code == 200
        assert _push(client, [_file("c.jsonl", "keep")], device_id=other_device)[0] == 200
        asyncio.run(_drain(h, processed=1, reviewed=1))

        status, body = _purge(client)

    assert status == 200
    assert body["data"] == {
        "device_id": DEVICE,
        "source_id": "cc-sessions",
        "purged": {"queued": 0, "processing": 0, "processed": 1, "pending_review": 1},
        "content_retained": True,
        "content_retention": "clickhouse_ttl_180d",
    }
    assert [row.device_id for row in h.queue.rows.values()] == [other_device]


def test_purge_is_idempotent_and_keeps_cursor(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复清理仍 200 且计数为 0；游标保留，同一内容不会被重新接收。"""
    first = _file("a.jsonl", "hello")
    with _provisioned(h, monkeypatch) as client:
        assert _push(client, [first], batch_id="b-1")[0] == 200
        assert _purge(client)[0] == 200
        status, body = _purge(client)
        assert status == 200
        assert body["data"]["purged"] == {
            "queued": 0,
            "processing": 0,
            "processed": 0,
            "pending_review": 0,
        }
        cursor = client.get(
            "/ingest/cursor",
            params={"device_id": DEVICE, "source_id": "cc-sessions"},
            headers=AUTH,
        ).json()["data"]
        assert cursor["files"][0]["offset"] == first["to_offset"]


@pytest.mark.parametrize(
    ("source_id", "device_id", "purge"),
    [
        ("cc-sessions", DEVICE, None),
        ("cc-sessions", DEVICE, "false"),
        ("cc-sessions", DEVICE, "yes"),
        ("cc-sessions", None, "true"),
        ("cc-sessions", "not-a-uuid", "true"),
        ("%2E%2E", DEVICE, "true"),
        ("a%20b", DEVICE, "true"),
        ("cc-sessions", "kb-console", "true"),
    ],
)
def test_purge_rejects_bad_parameters(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    source_id: str,
    device_id: str | None,
    purge: str | None,
) -> None:
    with _provisioned(h, monkeypatch) as client:
        _push(client, [_file("a.jsonl", "hello")])
        status, body = _purge(client, source_id, device_id=device_id, purge=purge)
        assert status == 400
        assert body["code"] == 1003
        assert len(h.queue.rows) == 1


def test_purge_is_recorded_in_write_audit(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    with _provisioned(h, monkeypatch) as client:
        _push(client, [_file("a.jsonl", "secret-body")])
        _purge(client)

    rows = [
        (row["actor"], row["project"], row["node_id"], row["action"], row["result"])
        for row in h.targets.audits
        if row["action"] == "ingest_purge"
    ]
    assert rows == [("provision", None, None, "ingest_purge", "ok")]
    assert PROVISION not in repr(rows)


# ---- 内部接口：管理台上传（MEMHUB_INTERNAL_TOKEN） ------------------------


def _internal_enqueue(
    client: TestClient,
    *,
    project: str = "sdp-tag",
    content: str = "hello",
    path: str = "note.md",
    headers: dict[str, str] | None = INTERNAL_AUTH,
    device_id: str = CONSOLE_DEVICE,
    source_type: str = "docs",
    batch_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    body = {
        "batch_id": batch_id or uuid.uuid4().hex,
        "device_id": device_id,
        "source_id": project,
        "source_type": source_type,
        "project": project,
        "files": [_file(path, content)],
    }
    response = client.post("/internal/enqueue", json=body, headers=headers)
    return response.status_code, cast(dict[str, Any], response.json())


def test_internal_endpoints_require_configured_token(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch) as client:
        status, body = _internal_enqueue(client)
        assert (status, body["code"]) == (500, 2001), "未配置内部 token 即关闭接口"
        assert h.queue.rows == {}


def test_internal_endpoint_rejects_wrong_token(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        status, body = _internal_enqueue(client, headers={"Authorization": "Bearer nope"})
        assert (status, body["code"]) == (401, 1001)
        assert h.queue.rows == {}


def test_internal_enqueue_lands_in_the_same_queue(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        status, body = _internal_enqueue(client)
        assert status == 200
        assert body["data"]["accepted"] == 1

        batch_id = body["data"]["batch_id"]
        progress = client.get(f"/internal/queue/{batch_id}", headers=INTERNAL_AUTH)
        assert progress.status_code == 200
        data = progress.json()["data"]
        assert data["project"] == "sdp-tag"
        assert data["counts"] == {
            "queued": 1,
            "processing": 0,
            "processed": 0,
            "pending_review": 0,
        }
        assert data["files"][0]["status"] == "queued"

    [row] = h.queue.rows.values()
    assert (row.producer, row.device_id, row.project) == ("console", CONSOLE_DEVICE, "sdp-tag")
    assert asyncio.run(h.content.get("sdp-tag", row.sha256)) == "hello"


def test_internal_enqueue_denies_unregistered_target(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        status, body = _internal_enqueue(client, project="ghost")
        assert status == 400
        assert body["data"] == {"reason": "unregistered"}
        assert h.queue.rows == {}


def test_internal_enqueue_rejects_collector_identity(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内部接口也走 console 生产者校验：不能让采集器身份混进来。"""
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        status, _body = _internal_enqueue(client, device_id=str(uuid.uuid4()))
        assert status == 400
        assert h.queue.rows == {}


def test_internal_queue_reports_worker_progress(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        _, created = _internal_enqueue(client, content="first", path="a.md")
        _, second = _internal_enqueue(client, content="second", path="b.md")
        asyncio.run(_drain(h, processed=1, reviewed=1))

        queued = client.get(f"/internal/queue/{created['data']['batch_id']}", headers=INTERNAL_AUTH)
        assert queued.status_code == 200
        queued_data = queued.json()["data"]
        assert (queued_data["counts"]["processed"], queued_data["status"]) == (1, "processed")

        reviewed = client.get(
            f"/internal/queue/{second['data']['batch_id']}", headers=INTERNAL_AUTH
        )
        reviewed_data = reviewed.json()["data"]
        assert reviewed_data["counts"]["pending_review"] == 1
        assert reviewed_data["files"][0]["attempts"] == 1
        assert reviewed_data["errors"] == ["boom"]


def test_internal_queue_unknown_and_ambiguous_batch(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serve(h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL) as client:
        missing = client.get("/internal/queue/deadbeef", headers=INTERNAL_AUTH)
        assert (missing.status_code, missing.json()["code"]) == (404, 1011)

        _, created = _internal_enqueue(client, project="sdp-tag")
        batch_id = created["data"]["batch_id"]
        # 指定了错误的库：批次不属于它，不能拿到别库的进度。
        wrong = client.get(
            f"/internal/queue/{batch_id}", params={"project": "other-kb"}, headers=INTERNAL_AUTH
        )
        assert wrong.status_code == 404
        resolved = client.get(
            f"/internal/queue/{batch_id}", params={"project": "sdp-tag"}, headers=INTERNAL_AUTH
        )
        assert resolved.status_code == 200
        assert resolved.json()["data"]["project"] == "sdp-tag"


def test_internal_enqueue_reports_queue_full(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    with _serve(
        h, monkeypatch, MEMHUB_INTERNAL_TOKEN=INTERNAL, MEMHUB_QUEUE_MAX_BYTES="1"
    ) as client:
        status, body = _internal_enqueue(client, content="larger than one byte")
        assert status == 503
        assert body["code"] == 1013
        assert body["data"] == {"used_bytes": 0, "limit_bytes": 1, "incoming_bytes": 20}
        assert h.queue.rows == {}
