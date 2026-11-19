"""采集 API。

存储由环境决定：设置了 `MEMHUB_DB_URL` 用共享 PG 实例（生产），否则退回进程内
`MemoryStore`（仅 dev 联调，重启即丢）。路由、信封、错误码在两种存储下完全一致。

启动：

    MEMHUB_DB_URL=postgresql://memhub_app@127.0.0.1:5432/memhub_prod \
      uvicorn memhub.ingest.app:create_app --factory --port 8700
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from memhub.contract import (
    Cursor,
    ErrorCode,
    FileCursor,
    IngestRequest,
    IngestResult,
    SourcesConfig,
)
from memhub.ingest.store import CursorConflict, MemoryStore, StateStore

HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.DEVICE_REVOKED: 403,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.CURSOR_CONFLICT: 409,
    ErrorCode.BATCH_TOO_LARGE: 413,
    ErrorCode.UNPARSABLE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.QUEUE_BACKPRESSURE: 503,
    ErrorCode.SCOPE_DENIED: 403,
    ErrorCode.INTERNAL: 500,
}


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        data: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class DeviceRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str | None = Field(
        default=None,
        pattern=r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    name: str = Field(min_length=1)
    platform: str = Field(min_length=1)


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    collector_version: str
    state: str = "running"
    sources: list[dict[str, Any]] = Field(default_factory=list)


class CursorData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_rev: int
    cursor: Cursor
    files: list[FileCursor]


def _ok(data: object) -> dict[str, object]:
    return {"code": 0, "message": "ok", "data": data}


def build_store() -> StateStore:
    """`MEMHUB_DB_URL` 有值即用 PG；否则退回内存实现（仅 dev）。"""
    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if not dsn:
        return MemoryStore()
    from memhub.ingest.postgres import PostgresStore

    return PostgresStore(dsn)


def create_app(store: StateStore | None = None) -> FastAPI:
    dev_token = os.environ.get("MEMHUB_DEV_TOKEN", "")
    state = store or build_store()
    app = FastAPI(title="memhub ingest", version="0.1.0")
    app.state.store = state

    def auth(authorization: str | None, device_id: str) -> None:
        """校验 Bearer 与 device 绑定；dev 下所有设备共享同一个 dev token。"""
        if not dev_token:
            raise ApiError(ErrorCode.TOKEN_INVALID, "server has no dev token configured")
        if authorization != f"Bearer {dev_token}":
            raise ApiError(ErrorCode.TOKEN_INVALID, "invalid device token")
        if not state.is_registered(device_id):
            raise ApiError(ErrorCode.DEVICE_REVOKED, "device not registered")

    @app.exception_handler(ApiError)
    async def on_api_error(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, ApiError):
            raise exc
        status = 500 if exc.code is ErrorCode.INTERNAL else HTTP_STATUS[exc.code]
        return JSONResponse(
            status_code=status,
            content={"code": int(exc.code), "message": exc.message, "data": exc.data},
        )

    @app.exception_handler(CursorConflict)
    async def on_cursor_conflict(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, CursorConflict):
            raise exc
        return JSONResponse(
            status_code=409,
            content={
                "code": int(ErrorCode.CURSOR_CONFLICT),
                "message": "cursor rollback",
                "data": {"path": exc.path, "expected_offset": exc.expected_offset},
            },
        )

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True}

    @app.post("/devices/register")
    def register(body: DeviceRegister) -> dict[str, object]:
        if not dev_token:
            raise ApiError(ErrorCode.INTERNAL, "server has no dev token configured")
        device_id = body.device_id or f"dev-{int(datetime.now(UTC).timestamp())}"
        state.register_device(device_id, name=body.name, platform=body.platform)
        return _ok(
            {
                "device_id": device_id,
                "device_token": dev_token,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    @app.get("/ingest/cursor")
    def cursor(
        device_id: Annotated[str, Query()],
        source_id: Annotated[str, Query()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        auth(authorization, device_id)
        source_rev, files = state.get_cursor(device_id, source_id)
        data = CursorData(
            source_id=source_id,
            source_rev=source_rev,
            cursor=state.cursor_summary(device_id, source_id),
            files=files,
        )
        return _ok(data.model_dump(mode="json"))

    @app.post("/ingest/raw")
    def raw(
        body: IngestRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        auth(authorization, body.device_id)
        for batch_file in body.files:
            if "\x00" in batch_file.content:
                raise ApiError(
                    ErrorCode.UNPARSABLE,
                    "binary content is not accepted",
                    {"path": batch_file.path},
                )
        result: IngestResult = state.apply(body)
        return _ok(result.model_dump(mode="json"))

    @app.post("/ingest/heartbeat")
    def heartbeat(
        body: Heartbeat,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        auth(authorization, body.device_id)
        return _ok({"commands": []})

    @app.get("/debug/sources")
    def debug_sources() -> dict[str, object]:
        """仅 dev：确认 sources.json 能被契约模型接受。"""
        path = os.environ.get("MEMHUB_SOURCES_PATH", "")
        if not path or not os.path.exists(path):
            raise ApiError(ErrorCode.BAD_REQUEST, "MEMHUB_SOURCES_PATH is not set")
        with open(path, encoding="utf-8") as handle:
            config = SourcesConfig.model_validate_json(handle.read())
        return _ok(config.model_dump(mode="json"))

    return app
