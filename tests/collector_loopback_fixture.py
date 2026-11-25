"""仅用于隔离客户端联调：回环 HTTP、内存登记、临时 PG schema 和 Fake worker。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from memhub.ingest.app import create_app as create_ingest
from memhub.ingest.store import MemoryStore
from memhub.kb.api import create_app as create_kb
from memhub.kb.models import Base
from memhub.kb.session import create_runtime_store
from memhub.worker.daemon import WorkerConfig, run_round

PROJECTS = ("fixture-left", "fixture-right", "fixture-denied")
QUOTE = "Use ceramic spacers to keep test boards separated during drying."


async def _create_schema(dsn: str, schema: str) -> None:
    url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()
    finally:
        await admin.dispose()


async def _drop_schema(dsn: str, schema: str) -> None:
    url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        await admin.dispose()


class Fake:
    async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
        # 只对联调约定的合成样本返回一条候选；不转发或显示输入。
        evidence = re.search(
            r'^\[(b\d+) user new\] "' + re.escape(QUOTE) + '"$', prompt, re.MULTILINE
        )
        nodes = []
        if evidence is not None:
            nodes.append(
                {
                    "kind": "procedure",
                    "title": "Separate boards during drying",
                    "slug": "separate-boards-during-drying",
                    "body": QUOTE,
                    "evidence": [{"block": evidence[1], "quote": QUOTE}],
                }
            )
        return json.dumps({"nodes": nodes, "edges": []})


async def serve(root: Path, device: str, port: int) -> None:
    dsn = os.environ.get("MEMHUB_TEST_DB_URL", "")
    if not dsn:
        raise SystemExit("联调夹具需要 MEMHUB_TEST_DB_URL（kb 真源在 PG）")
    knowledge = root / "knowledge"
    data = root / "data"
    for project in PROJECTS:
        (knowledge / project).mkdir(parents=True)
    # 采集侧仍按目录登记判目标；kb 真源与 worker 一律走 PG。
    registered = PROJECTS[:2]
    (knowledge / ".kbs.json").write_text(
        json.dumps({"kbs": [{"id": project} for project in registered]}), encoding="utf-8"
    )
    for key in tuple(os.environ):
        if key.startswith("MEMHUB_"):
            del os.environ[key]
    schema = f"fixture_{uuid4().hex[:12]}"
    await _create_schema(dsn, schema)
    store = create_runtime_store(dsn=dsn, schema=schema)
    for project in registered:
        await store.register_project(project)
    os.environ.update(
        MEMHUB_ENV="dev",
        MEMHUB_KB_DB_URL=dsn,
        MEMHUB_KNOWLEDGE_DIR=str(knowledge),
        MEMHUB_DATA_DIR=str(data),
        MEMHUB_KB_AUTO_REBUILD="0",
        MEMHUB_KB_GRAPH=str(root / "unused-graph.json"),
        MEMHUB_KB_API_URL=f"http://127.0.0.1:{port}",
        MEMHUB_DEV_TOKEN=secrets.token_hex(32),
    )
    state = MemoryStore()
    app = create_kb(schema=schema)
    # 先注册管理台路由，再挂载采集应用，保留各自的错误信封。
    app.mount("/api/v1", create_ingest(state))
    config = WorkerConfig(data, store, "fake", is_registered=state.is_registered)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def worker() -> None:
        fake = Fake()
        while True:
            await run_round(fake, config)
            await asyncio.sleep(1)

    worker_task = asyncio.create_task(worker())
    try:
        await server.serve()
    finally:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await store.aclose()
        await _drop_schema(dsn, schema)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True, type=UUID, help="一次性测试设备的 UUID v4")
    parser.add_argument("--port", default=8780, type=int)
    args = parser.parse_args()
    if args.device_id.version != 4:
        parser.error("--device-id 必须是 UUID v4")
    if not 1024 <= args.port <= 65535:
        parser.error("--port 必须在 1024–65535")
    with TemporaryDirectory(prefix="memhub-collector-fixture-") as temp:
        asyncio.run(serve(Path(temp), str(args.device_id), args.port))


if __name__ == "__main__":
    main()
