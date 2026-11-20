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

import httpx
from anyio import Path as AsyncPath
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from memhub.contract import (
    KB_ID_RE,
    PROJECT_AUTO,
    Cursor,
    ErrorCode,
    FileCursor,
    IngestRequest,
    IngestResult,
    SourcesConfig,
    valid_project,
)
from memhub.ingest.store import CursorConflict, MemoryStore, StateStore
from memhub.queue.rawstore import (
    QuotaExceeded,
    RawStoreQuota,
    estimate_new_bytes,
    save_batch,
)

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
    # 知识库代理（/ingest/projects）透传 kb-api 的业务码，桌面端要能区分
    # 「id 冲突」「库不存在」「参数非法」。
    ErrorCode.KB_CONFLICT: 409,
    ErrorCode.KB_NOT_FOUND: 404,
    ErrorCode.KB_INVALID: 422,
    ErrorCode.KB_QUEUE_FULL: 503,
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


class ProjectCreate(BaseModel):
    """桌面端「新建知识库」：id 即真源一级目录名，名称/描述进 `.kbs.json`。"""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)


DEFAULT_KB_API_URL = "http://127.0.0.1:8701"


async def _kb_api_request(
    base_url: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> Any:
    """把知识库列表/新建转发给 kb-api。

    知识真源只有 kb-api 一个写者（`.kbs.json` 是读改写），采集端不直接碰盘；
    host 网络下 127.0.0.1:8701 可达，kb 未起时这里返回 500，桌面端可回退手填 id。
    """
    url = base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as http:
            response = await http.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        raise ApiError(ErrorCode.INTERNAL, f"知识库服务不可达：{exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:200]}
    if response.status_code >= 400:
        upstream_code = body.get("code") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        # kb-api 用同一套 ErrorCode（1010 冲突 / 1011 不存在 / 1012 非法），
        # 认出就原样透传，桌面端才能把「已存在」和「参数错」分开提示。
        code: ErrorCode | None = None
        try:
            parsed = ErrorCode(int(upstream_code))  # type: ignore[arg-type]
        except (TypeError, ValueError, KeyError):
            parsed = None
        if parsed is not None and parsed is not ErrorCode.OK:
            code = parsed
        else:
            # 不认识的响应（网关/异常页）：5xx 算上游故障，其余算请求问题。
            code = ErrorCode.INTERNAL if response.status_code >= 500 else ErrorCode.BAD_REQUEST
        raise ApiError(code, str(message or "知识库请求失败"), {"upstream": response.status_code})
    return body


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


DEFAULT_QUEUE_MAX_BYTES = 1024**3


def _env_bytes(name: str, default: int) -> int:
    """读字节数配置；非法值直接启动失败，而不是悄悄退回默认值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数（字节数）：{raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} 必须大于 0：{value}")
    return value


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
    # 即便当前没配 DATA_DIR 也要校验：配错的值应该在启动时就炸，而不是等哪天补上
    # DATA_DIR 后突然把某个上限换成另一个数。
    queue_max = _env_bytes("MEMHUB_QUEUE_MAX_BYTES", DEFAULT_QUEUE_MAX_BYTES)
    quota = RawStoreQuota(raw_root / "raw_store", queue_max) if raw_root is not None else None
    state = store or build_store()
    kb_api_url = os.environ.get("MEMHUB_KB_API_URL", DEFAULT_KB_API_URL)
    app = FastAPI(title="memhub ingest", version="0.1.0")
    app.state.store = state

    async def auth(authorization: str | None, device_id: str) -> None:
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
        if not await state.is_registered(device_id):
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
    async def healthz() -> dict[str, object]:
        return {"ok": True}

    @app.post("/devices/register")
    async def register(
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
        await state.register_device(device_id, name=body.name, platform=body.platform)
        token = issue_device_token(token_secret, device_id) if token_secret else dev_token
        return _ok(
            {
                "device_id": device_id,
                "device_token": token,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    @app.get("/ingest/cursor")
    async def cursor(
        device_id: Annotated[str, Query()],
        source_id: Annotated[str, Query()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await auth(authorization, device_id)
        source_rev, files = await state.get_cursor(device_id, source_id)
        data = CursorData(
            source_id=source_id,
            source_rev=source_rev,
            cursor=await state.cursor_summary(device_id, source_id),
            files=files,
        )
        return _ok(data.model_dump(mode="json"))

    @app.get("/ingest/projects")
    async def list_projects(
        device_id: Annotated[str, Query()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        """桌面端选知识库用的列表（已有知识库），转发 kb-api 的同一份数据。"""
        await auth(authorization, device_id)
        return _ok(await _kb_api_request(kb_api_url, "GET", "/api/v1/kb/projects"))

    @app.post("/ingest/projects", status_code=201)
    async def create_project(
        body: ProjectCreate,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        """桌面端「新建知识库」；之后采集端用同一个 id 作为 project 推送。"""
        await auth(authorization, body.device_id)
        # auto 是推送侧的保留值（回退按 source_id 归档），不是真正可以建的库；
        # 放行会建出一个名叫 auto 的目录，之后谁也没法引用它。
        # 「格式非法」和「用了保留值」分开报：客户端要靠 reason 区分提示文案，
        # 别让前端去解析 message。
        if body.id == PROJECT_AUTO:
            raise ApiError(
                ErrorCode.BAD_REQUEST,
                "auto 是推送侧的保留值（表示按源 id 归档），不能用作知识库 id",
                {"id": body.id, "reason": "reserved"},
            )
        if not KB_ID_RE.fullmatch(body.id):
            raise ApiError(
                ErrorCode.BAD_REQUEST,
                "知识库 id 只能用小写字母/数字/./_/-，以字母或数字开头，≤64 位",
                {"id": body.id, "reason": "invalid"},
            )
        created = await _kb_api_request(
            kb_api_url,
            "POST",
            "/api/v1/kb/projects",
            {"id": body.id, "name": body.name or body.id, "description": body.description},
        )
        return _ok(created)

    @app.post("/ingest/raw")
    async def raw(
        body: IngestRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await auth(authorization, body.device_id)
        if not valid_project(body.project):
            # project 直接变成真源目录名：白名单之外的串一律拒绝，不做静默兜底，
            # 否则采集端以为写进了某个库、实际落到了别处。
            raise ApiError(
                ErrorCode.BAD_REQUEST,
                "project 必须是 auto 或知识库 id（小写字母/数字/./_/-，以字母或数字开头，≤64 位）",
                {"project": body.project},
            )
        for batch_file in body.files:
            if "\x00" in batch_file.content:
                raise ApiError(
                    ErrorCode.UNPARSABLE,
                    "binary content is not accepted",
                    {"path": batch_file.path},
                )
        if raw_root is not None and quota is not None:
            # 配额在落盘前判断：满了就 1008 让采集端降级，绝不把磁盘写满。
            # 估算只算新 sha——重放已收下的批次不受影响，否则客户端会永久卡死。
            incoming = await estimate_new_bytes(raw_root, body)
            try:
                await quota.check(incoming)
            except QuotaExceeded as exc:
                raise ApiError(
                    ErrorCode.QUEUE_BACKPRESSURE,
                    "raw_store quota exceeded",
                    {
                        "used_bytes": exc.used,
                        "limit_bytes": exc.limit,
                        "incoming_bytes": exc.incoming,
                    },
                ) from exc
            # 先落盘再 apply：apply 的后续校验失败只会留下无害的内容寻址孤儿文件，
            # 而反过来（先 apply 后落盘）一旦落盘失败，重放就再也补不回落盘的字节。
            try:
                await save_batch(raw_root, body)
            except OSError:
                # 可能只写了一半；让下次请求重扫，别让缓存低估占用。
                await quota.invalidate()
                raise
            await quota.record(incoming)
        result: IngestResult = await state.apply(body)
        return _ok(result.model_dump(mode="json"))

    @app.post("/ingest/heartbeat")
    async def heartbeat(
        body: Heartbeat,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await auth(authorization, body.device_id)
        return _ok({"commands": []})

    @app.get("/debug/sources")
    async def debug_sources() -> dict[str, object]:
        """仅 dev：确认 sources.json 能被契约模型接受。"""
        path = os.environ.get("MEMHUB_SOURCES_PATH", "")
        if not path or not await AsyncPath(path).is_file():
            raise ApiError(ErrorCode.BAD_REQUEST, "MEMHUB_SOURCES_PATH is not set")
        config = SourcesConfig.model_validate_json(
            await AsyncPath(path).read_text(encoding="utf-8")
        )
        return _ok(config.model_dump(mode="json"))

    return app
