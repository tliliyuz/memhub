"""知识库上传：把文件送进提炼队列（ADR-0020）。

上传只是把「本地有 agent 采集」换成「人在管理台贴文件」：kb-api 做文件校验
（后缀、UTF-8、大小、数量），随后调用 ingest 的内部接口 `POST /internal/enqueue`；
正文、队列、配额都由 ingest 统一处理，kb-api 不再直写本机目录，也不持有运行态
DSN 或 ClickHouse 凭据。

批次状态读 `GET /internal/queue/{batch_id}`，由队列行推导，不再有本地清单与
`failures.json`。对外形状保持管理台契约：`queued / processed / failed / missing`。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from starlette.datastructures import UploadFile

from memhub.contract import BatchFile, IngestRequest, explicit_project
from memhub.queue.identity import CONSOLE_DEVICE

DEVICE_ID = CONSOLE_DEVICE
SOURCE_TYPE = "docs"
MAX_FILES = 20
MAX_CHARS = 60_000
ALLOWED_SUFFIXES = (".md", ".txt", ".jsonl")
BATCH_ID_RE = re.compile(r"^[0-9a-f]{32}$")

UploadFileStatus = Literal["queued", "processed", "failed", "missing"]
_STATUS_MAP: dict[str, UploadFileStatus] = {
    "queued": "queued",
    "processing": "queued",
    "processed": "processed",
    "pending_review": "failed",
}


class UploadInvalid(Exception):
    """整批请求不合法：字段缺失、项目 id 非法、没有可接受的文件。"""

    def __init__(self, message: str, data: dict[str, Any] | None = None, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.data = data or {}
        self.status = status


class UploadQueueFull(Exception):
    """提炼队列已到上限：让上传方稍后再试，不把队列撑爆。"""

    def __init__(self, used: int, limit: int, incoming: int) -> None:
        super().__init__(f"queue full: {used}+{incoming} > {limit}")
        self.used = used
        self.limit = limit
        self.incoming = incoming


class IngestUnavailable(RuntimeError):
    """ingest 内部接口不可达或内部 token 配置错误，上传整体不可用。"""


class KbUploads:
    """ingest 内部接口的客户端；进程内共享一个连接池。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=5.0),
            transport=transport,
            trust_env=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    # ---- 上传 ----

    async def accept(
        self,
        project: str,
        files: Sequence[UploadFile],
        *,
        project_exists: Callable[[str], Awaitable[bool]],
    ) -> dict[str, Any]:
        if explicit_project(project) is None:
            raise UploadInvalid(
                "知识库 id 只能用小写字母/数字/./_/-，且以字母或数字开头",
                {"project": project},
                status=422,
            )
        # 只收已存在的知识库：拼错的 project 不能凭空建出一个空库。
        if not await project_exists(project):
            raise UploadInvalid(f"知识库不存在: {project}", {"project": project}, status=404)
        if not files:
            raise UploadInvalid("至少上传一个文件", {"files": "empty"}, status=422)
        if len(files) > MAX_FILES:
            raise UploadInvalid(f"单批最多 {MAX_FILES} 个文件", {"files": len(files)}, status=422)

        accepted: list[BatchFile] = []
        rejected: list[dict[str, str]] = []
        for upload in files:
            name = Path(upload.filename or "").name
            suffix = Path(name).suffix.lower()
            if not name:
                rejected.append({"name": "", "reason": "invalid_name"})
                continue
            if suffix not in ALLOWED_SUFFIXES:
                rejected.append({"name": name, "reason": "unsupported_type"})
                continue
            raw = await upload.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                rejected.append({"name": name, "reason": "not_utf8"})
                continue
            if not content.strip():
                rejected.append({"name": name, "reason": "empty"})
                continue
            if len(content) > MAX_CHARS:
                rejected.append({"name": name, "reason": "too_large"})
                continue
            encoded = content.encode("utf-8")
            accepted.append(
                BatchFile(
                    path=name,
                    from_offset=0,
                    to_offset=len(encoded),
                    mtime=datetime.now(UTC),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                    content=content,
                )
            )

        if not accepted:
            raise UploadInvalid(
                "没有可接受的文本文件（仅支持 .md / .txt / .jsonl，UTF-8，单文件 ≤60000 字符）",
                {"rejected": rejected},
                status=422,
            )

        batch_id = uuid.uuid4().hex
        request = IngestRequest(
            batch_id=batch_id,
            device_id=DEVICE_ID,
            source_id=project,
            source_type=SOURCE_TYPE,
            project=project,
            files=accepted,
        )
        await self._enqueue(request)
        return {
            "batch_id": batch_id,
            "project": project,
            "accepted": [
                {
                    "name": batch_file.path,
                    "sha256": batch_file.sha256,
                    "chars": len(batch_file.content),
                }
                for batch_file in accepted
            ],
            "rejected": rejected,
            "queued": True,
        }

    # ---- 状态 ----

    async def status(self, batch_id: str) -> dict[str, Any]:
        if not BATCH_ID_RE.match(batch_id):
            raise UploadInvalid("批次 id 非法", {"batch_id": batch_id}, status=404)
        data = await self._call("GET", f"/internal/queue/{batch_id}")
        counts: dict[UploadFileStatus, int] = {
            "queued": 0,
            "processed": 0,
            "failed": 0,
            "missing": 0,
        }
        entries: list[dict[str, Any]] = []
        raw_counts = data.get("counts")
        raw_files = data.get("files")
        if isinstance(raw_counts, dict):
            counts["queued"] = int(raw_counts.get("queued", 0)) + int(
                raw_counts.get("processing", 0)
            )
            counts["processed"] = int(raw_counts.get("processed", 0))
            counts["failed"] = int(raw_counts.get("pending_review", 0))
        for item in raw_files if isinstance(raw_files, list) else []:
            if not isinstance(item, dict):
                continue
            state = _STATUS_MAP.get(str(item.get("status")), "missing")
            entry: dict[str, Any] = {
                "name": str(item.get("name", "")),
                "sha256": str(item.get("sha256", "")),
                "status": state,
            }
            attempts = item.get("attempts")
            if state == "failed" and isinstance(attempts, int):
                entry["attempts"] = attempts
            entries.append(entry)
        return {
            "batch_id": str(data.get("batch_id", batch_id)),
            "project": str(data.get("project", "")),
            "created_at": str(data.get("created_at") or ""),
            "total": int(data.get("total", len(entries))),
            "counts": counts,
            "files": entries,
        }

    # ---- HTTP ----

    async def _enqueue(self, request: IngestRequest) -> dict[str, Any]:
        return await self._call("POST", "/internal/enqueue", json=request.model_dump(mode="json"))

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self.client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise IngestUnavailable("ingest unreachable") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code >= 400:
            data = body.get("data")
            payload = data if isinstance(data, dict) else {}
            try:
                code = int(body.get("code", 0))
            except (TypeError, ValueError):
                code = 0
            if code == 1013:
                raise UploadQueueFull(
                    int(payload.get("used_bytes", 0)),
                    int(payload.get("limit_bytes", 0)),
                    int(payload.get("incoming_bytes", 0)),
                )
            if response.status_code == 404:
                raise UploadInvalid(
                    f"批次不存在: {path.rsplit('/', 1)[-1]}",
                    {"batch_id": path.rsplit("/", 1)[-1]},
                    status=404,
                )
            if response.status_code == 400:
                raise UploadInvalid(
                    str(body.get("message") or "上传请求被拒绝"), payload, status=400
                )
            raise IngestUnavailable(f"ingest http {response.status_code}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise IngestUnavailable("ingest returned invalid envelope")
        return data


__all__ = [
    "ALLOWED_SUFFIXES",
    "BATCH_ID_RE",
    "MAX_CHARS",
    "MAX_FILES",
    "IngestUnavailable",
    "KbUploads",
    "UploadInvalid",
    "UploadQueueFull",
]
