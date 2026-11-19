"""采集 API。

存储由环境决定：设置了 `MEMHUB_DB_URL` 用共享 PG 实例（生产），否则退回进程内
`MemoryStore`（仅 dev 联调，重启即丢）。路由、信封、错误码在两种存储下完全一致。

启动：

    MEMHUB_DB_URL=postgresql://memhub_app@127.0.0.1:5432/memhub_prod \
      uvicorn memhub.ingest.app:create_app --factory --port 8700
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime
from pathlib import Path
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
from memhub.ingest.rawstore import save_batch
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


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def issue_device_token(secret: str, device_id: str) -> str:
    """`v1.<device_id>.<HMAC>`：token 与设备绑定，服务端可无状态校验。

    共享 dev token 只用于本地联调；生产每个设备一枚，泄露只影响该设备，
    吊销走 devices.revoked_at（auth 里查）。
    """
    mac = hmac.new(secret.encode(), device_id.encode(), hashlib.sha256).digest()
    return f"v1.{_b64(device_id.encode())}.{_b64(mac[:24])}"


def verify_device_token(secret: str, token: str, device_id: str) -> bool:
    try:
        version, encoded_id, _mac = token.split(".")
        if version != "v1":
            return False
        padded = encoded_id + "=" * (-len(encoded_id) % 4)
        if base64.urlsafe_b64decode(padded.encode()).decode() != device_id:
            return False
    except (ValueError, UnicodeDecodeError):
        return False
    expected = issue_device_token(secret, device_id)
    return hmac.compare_digest(expected, token)


def build_store() -> StateStore:
    """`MEMHUB_DB_URL` 有值即用 PG；否则退回内存实现（仅 dev）。"""
    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if not dsn:
        return MemoryStore()
    from memhub.ingest.postgres import PostgresStore

    return PostgresStore(dsn)


def create_app(store: StateStore | None = None) -> FastAPI:
    prod = os.environ.get("MEMHUB_ENV") == "prod"
    # 文档约定：prod 下忽略 MEMHUB_DEV_TOKEN，避免误配成共享后门。
    dev_token = "" if prod else os.environ.get("MEMHUB_DEV_TOKEN", "")
    token_secret = os.environ.get("MEMHUB_DEVICE_TOKEN_SECRET", "")
    provision_token = os.environ.get("MEMHUB_PROVISION_TOKEN", "")
    data_dir = os.environ.get("MEMHUB_DATA_DIR", "")
    if prod and not data_dir:
        # 生产没有 DATA_DIR 意味着原始增量无处可落：宁可不启动，也不要静默丢数据。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_DATA_DIR")
    if prod and not token_secret:
        # 没有签发密钥就只能共享 dev token，等于任何设备都能冒领。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_DEVICE_TOKEN_SECRET")
    if prod and not provision_token:
        # 开放注册 = 任何人自助领 token 往知识库里灌内容。契约要求注册是用户态操作，
        # 用户体系还没做，先用 provision token 把口子关上。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_PROVISION_TOKEN")
    raw_root = Path(data_dir) if data_dir else None
    state = store or build_store()
    app = FastAPI(title="memhub ingest", version="0.1.0")
    app.state.store = state

    def auth(authorization: str | None, device_id: str) -> None:
        """校验 token 与 device 绑定。

        生产：`v1.<device>.<HMAC>`，签名密钥来自环境，token 与设备一一对应；
        本地联调：所有设备共享 `MEMHUB_DEV_TOKEN`（该路径在生产配置下不可用）。
        """
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        accepted = bool(
            (dev_token and hmac.compare_digest(supplied, dev_token))
            or (token_secret and verify_device_token(token_secret, supplied, device_id))
        )
        if not accepted:
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
    def register(
        body: DeviceRegister,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        if not token_secret and not dev_token:
            raise ApiError(ErrorCode.INTERNAL, "server has no device token configured")
        if provision_token:
            supplied = ""
            if authorization and authorization.startswith("Bearer "):
                supplied = authorization.removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, provision_token):
                raise ApiError(ErrorCode.TOKEN_INVALID, "invalid provision token")
        if prod and body.device_id is None:
            # 契约 0.3：生产的 device_id 必填；服务端自动生成只留给 dev stub。
            raise ApiError(ErrorCode.BAD_REQUEST, "device_id is required in prod")
        device_id = body.device_id or f"dev-{int(datetime.now(UTC).timestamp())}"
        state.register_device(device_id, name=body.name, platform=body.platform)
        token = issue_device_token(token_secret, device_id) if token_secret else dev_token
        return _ok(
            {
                "device_id": device_id,
                "device_token": token,
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
        if raw_root is not None:
            # 先落盘再 apply：apply 的后续校验失败只会留下无害的内容寻址孤儿文件，
            # 而反过来（先 apply 后落盘）一旦落盘失败，重放就再也补不回落盘的字节。
            save_batch(raw_root, body)
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
