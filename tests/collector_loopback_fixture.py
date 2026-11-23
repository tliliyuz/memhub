"""仅用于隔离客户端联调：回环 HTTP、内存登记、临时真源和 Fake worker。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import uvicorn

from memhub.ingest.app import create_app as create_ingest
from memhub.ingest.store import MemoryStore
from memhub.kb.api import create_app as create_kb
from memhub.worker.daemon import WorkerConfig, run_round

PROJECTS = ("fixture-left", "fixture-right", "fixture-denied")
QUOTE = "Use ceramic spacers to keep test boards separated during drying."


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
    knowledge = root / "knowledge"
    data = root / "data"
    for project in PROJECTS:
        (knowledge / project).mkdir(parents=True)
    # 只登记前两个库：fixture-denied 目录存在但未登记，上传必须被拒绝。
    registered = PROJECTS[:2]
    (knowledge / ".kbs.json").write_text(
        json.dumps({"kbs": [{"id": project} for project in registered]}), encoding="utf-8"
    )
    for key in tuple(os.environ):
        if key.startswith("MEMHUB_"):
            del os.environ[key]
    os.environ.update(
        MEMHUB_ENV="dev",
        MEMHUB_KNOWLEDGE_DIR=str(knowledge),
        MEMHUB_DATA_DIR=str(data),
        MEMHUB_KB_AUTO_REBUILD="0",
        MEMHUB_KB_GRAPH=str(root / "unused-graph.json"),
        MEMHUB_KB_API_URL=f"http://127.0.0.1:{port}",
        MEMHUB_DEV_TOKEN=secrets.token_hex(32),
    )
    state = MemoryStore()
    app = create_kb()
    # 先注册管理台路由，再挂载采集应用，保留各自的错误信封。
    app.mount("/api/v1", create_ingest(state))
    config = WorkerConfig(data, knowledge, "fake", is_registered=state.is_registered)
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
