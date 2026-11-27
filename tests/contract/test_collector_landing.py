"""用合成会话验证 HTTP → PG 队列/CH 正文 → worker → 指定知识库，不联网调用模型。"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.ingest.app import create_app
from memhub.ingest.store import MemoryStore
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.queue.content import LocalContentStore
from memhub.queue.tasks import MemoryQueue
from memhub.worker.daemon import WorkerConfig, run_round

PROJECTS = ("fixture-left", "fixture-right", "fixture-denied")


@pytest.fixture
async def store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pg = PgKnowledgeStore(create_sessionmaker(kb_engine))
    for project in PROJECTS[:2]:
        await pg.register_project(project)
    return pg


class Fake:
    calls = 0

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
        self.calls += 1
        assert "[b0001 user new]" in prompt
        assert "ScratchPad" not in prompt
        quote = "Use ceramic spacers to keep test boards separated during drying."
        assert quote in prompt
        return json.dumps(
            {
                "nodes": [
                    {
                        "kind": "procedure",
                        "title": "Separate boards during drying",
                        "slug": "separate-boards-during-drying",
                        "body": quote,
                        "evidence": [{"block": "b0001", "quote": quote}],
                    }
                ],
                "edges": [],
            }
        )


async def test_selected_target_is_the_only_landing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: PgKnowledgeStore
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    device = str(uuid.uuid4())
    monkeypatch.setenv("MEMHUB_ENV", "dev")
    # `fixture-denied` 未登记：这正是当初被隐式建库的事故形态；目标只认 `kb_projects`。
    # 随机测试凭据仅留在本地进程内；不用任何操作系统已保存凭据。
    token = uuid.uuid4().hex
    monkeypatch.setenv("MEMHUB_DEV_TOKEN", token)
    state = MemoryStore()
    await state.register_device(device)
    queue = MemoryQueue()
    content_store = LocalContentStore(data / "content_store")
    content = (
        "\n".join(
            json.dumps(item)
            for item in [
                {"type": "user", "isMeta": True, "message": {"content": "ScratchPad"}},
                {
                    "type": "user",
                    "message": {
                        "content": "Use ceramic spacers to keep test boards separated during drying."
                    },
                },
            ]
        )
        + "\n"
    )
    sha = hashlib.sha256(content.encode()).hexdigest()
    body = {
        "batch_id": str(uuid.uuid4()),
        "device_id": device,
        "source_id": "fixture-source",
        "project": "fixture-denied",
        "source_type": "sessions",
        "files": [
            {
                "path": "fixture.jsonl",
                "sha256": sha,
                "content": content,
                "from_offset": 0,
                "to_offset": len(content.encode()),
                "mtime": "2026-01-01T00:00:00Z",
            }
        ],
    }
    app = create_app(state, queue=queue, content=content_store, kb_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
        trust_env=False,
    ) as client:
        denied = await client.post("/ingest/raw", json=body)
        assert denied.status_code == 400
        assert denied.json()["data"] == {"reason": "unregistered"}
        assert queue.rows == {}
        assert await content_store.get("fixture-denied", sha) is None
        assert (await state.get_cursor(device, "fixture-source"))[1] == []
        accepted = await client.post("/ingest/raw", json=body | {"project": "fixture-right"})
        assert accepted.status_code == 200
    [queued] = queue.rows.values()
    assert (queued.project, queued.status) == ("fixture-right", "queued")
    assert await content_store.get("fixture-right", sha) == content
    fake = Fake()
    report = await run_round(
        fake,
        WorkerConfig(
            queue=queue,
            content=content_store,
            store=store,
            model="fake",
            is_registered=state.is_registered,
        ),
    )
    assert (report.processed, report.created, report.failed, fake.calls) == (1, 1, 0, 1)
    assert await store.list_ids() == ["fixture-right/procedure/separate-boards-during-drying"]
    node, _ = await store.read("fixture-right/procedure/separate-boards-during-drying")
    assert node.tier == "canonical"
    assert [(source.device, source.ref) for source in node.source] == [(device, "fixture.jsonl")]
    assert queued.status == "processed"
    assert queued.processed_at is not None
