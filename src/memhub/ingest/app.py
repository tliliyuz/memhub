"""采集 API。

存储由环境决定：设置了 `MEMHUB_DB_URL` 用共享 PG 实例（生产），否则退回进程内
`MemoryStore`（仅 dev 联调，重启即丢）。采集目标登记一律读 PG 的 `kb_projects`
（`MEMHUB_KB_DB_URL`，只读；规格 §9.2.4）。路由、信封、错误码在两种状态存储下完全一致。

启动：

    MEMHUB_DB_URL=postgresql://memhub_app@127.0.0.1:5432/memhub_prod \
      uvicorn memhub.ingest.app:create_app --factory --port 8700
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from anyio import Path as AsyncPath
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from memhub.contract import (
    PROJECT_AUTO,
    Cursor,
    ErrorCode,
    FileCursor,
    IngestRequest,
    IngestResult,
    SourcesConfig,
    explicit_project,
)
from memhub.ingest.store import CursorConflict, MemoryStore, StateStore
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KB_SCHEMA, create_runtime_store
from memhub.kb.target_access import (
    TargetRegistry,
    TargetStatus,
    TargetUnavailable,
    target_status,
)
from memhub.queue.content import (
    ContentUnavailable,
    NullContentStore,
    RawContentStore,
    build_content_store,
)
from memhub.queue.flow import build_queue, enqueue_batch
from memhub.queue.identity import BatchTargetConflict, collector_device_reserved
from memhub.queue.tasks import (
    BatchItem,
    BatchProgress,
    QueueStore,
    QuotaExceeded,
)

LOGGER = logging.getLogger("memhub.ingest.audit")


def _ingest_lifespan(
    owned: list[Callable[[], Awaitable[None]]],
) -> Any:
    """应用自建的资源随生命周期释放；注入的资源由调用方负责。"""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            for close in owned:
                await close()

    return lifespan


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
    # kb-api 的业务码原样透传给桌面端（列表读取时仍可能出现）。
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


def _as_optional_project(value: object) -> str | None:
    # 不让 Pydantic 在鉴权前用 422 回显非字符串目标；路由统一处理目标不可用。
    return value if isinstance(value, str) else None


class RawIngestRequest(IngestRequest):
    project: Annotated[str | None, BeforeValidator(_as_optional_project)] = None


DEFAULT_KB_API_URL = "http://127.0.0.1:8701"
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_DEVICE_ID = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


async def _kb_api_request(
    base_url: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> Any:
    """向 kb-api 读取知识库列表（采集端只读，不代理建库）。

    知识真源只有 kb-api 一个写者（`.kbs.json` 是读改写），采集端不直接碰盘；
    host 网络下 127.0.0.1:8701 可达，kb 未起时这里返回通用 500。
    """
    url = base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as http:
            response = await http.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        raise _target_lookup_failed() from exc
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:200]}
    if response.status_code >= 500:
        raise _target_lookup_failed()
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
        if parsed is ErrorCode.INTERNAL:
            raise _target_lookup_failed()
        # 其余未识别的响应按请求问题处理。
        code = parsed if parsed and parsed is not ErrorCode.OK else ErrorCode.BAD_REQUEST
        raise ApiError(code, str(message or "知识库请求失败"), {"upstream": response.status_code})
    return body


_TARGET_MESSAGES: dict[str, str] = {
    "missing": "上传必须显式指定目标知识库（project 不能为空）",
    "reserved": "auto 是旧推送协议的保留值，不能作为知识库 id",
    "invalid": "知识库 id 只能用小写字母/数字/./_/-，并以字母或数字开头",
    "unregistered": "目标知识库未登记，请先在管理台建库",
    "inactive": "目标知识库当前不可写（已归档或被禁用）",
    "target_conflict": "与已落盘批次的采集目标不一致",
}


def _target_unavailable(reason: str) -> ApiError:
    message = _TARGET_MESSAGES.get(reason, "target unavailable")
    return ApiError(ErrorCode.BAD_REQUEST, message, {"reason": reason})


def _target_lookup_failed() -> ApiError:
    return ApiError(ErrorCode.INTERNAL, "无法确认知识库登记状态，请稍后重试")


def _ok(data: object) -> dict[str, object]:
    return {"code": 0, "message": "ok", "data": data}


def _progress_payload(
    project: str, progress: BatchProgress, items: list[BatchItem]
) -> dict[str, object]:
    return {
        "batch_id": progress.batch_id,
        "project": project,
        "total": progress.total,
        "status": progress.status,
        "counts": {
            "queued": progress.queued,
            "processing": progress.processing,
            "processed": progress.processed,
            "pending_review": progress.pending_review,
        },
        "errors": list(progress.errors),
        "created_at": (
            progress.created_at.astimezone(UTC).isoformat() if progress.created_at else None
        ),
        "files": [
            {
                "name": item.name,
                "sha256": item.sha256,
                "status": item.status,
                "attempts": item.attempts,
            }
            for item in items
        ],
    }


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


def create_app(
    store: StateStore | None = None,
    *,
    queue: QueueStore | None = None,
    content: RawContentStore | None = None,
    kb_store: PgKnowledgeStore | None = None,
    schema: str | None = KB_SCHEMA,
) -> FastAPI:
    """组装采集应用；目标登记一律读 `kb_projects`（规格 §9.2.4）。

    默认按 `MEMHUB_KB_DB_URL` 强制构造 PG 存储，缺 DSN 启动即抛 `KbDsnMissing`；
    `kb_store` 与 `schema` 供测试注入与隔离。采集侧只读该表，不写知识真源。

    `queue` / `content` 可注入；缺省按环境构造：生产必须有 `MEMHUB_DB_URL`
    （队列）与 `MEMHUB_CH_URL`（正文），否则启动即失败，不退回本机文件。
    """
    prod = os.environ.get("MEMHUB_ENV") == "prod"
    # 文档约定：prod 下忽略 MEMHUB_DEV_TOKEN，避免误配成共享后门。
    dev_token = "" if prod else os.environ.get("MEMHUB_DEV_TOKEN", "")
    token_secret = os.environ.get("MEMHUB_DEVICE_TOKEN_SECRET", "")
    provision_token = os.environ.get("MEMHUB_PROVISION_TOKEN", "")
    internal_token = os.environ.get("MEMHUB_INTERNAL_TOKEN", "")
    data_dir = os.environ.get("MEMHUB_DATA_DIR", "")
    if prod and not token_secret:
        # 没有签发密钥就只能共享 dev token，等于任何设备都能冒领。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_DEVICE_TOKEN_SECRET")
    if prod and not provision_token:
        # 开放注册 = 任何人自助领 token 往知识库里灌内容。契约要求注册是用户态操作，
        # 用户体系还没做，先用 provision token 把口子关上。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_PROVISION_TOKEN")
    if prod and not os.environ.get("MEMHUB_DB_URL", "").strip():
        # 队列真源在 PG，缺 DSN 时 raw 会落下来但没人提炼。宁可不启动。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_DB_URL")
    if prod and not os.environ.get("MEMHUB_CH_URL", "").strip():
        # 正文真源在 ClickHouse，缺它就是丢原文。宁可不启动。
        raise RuntimeError("MEMHUB_ENV=prod 必须设置 MEMHUB_CH_URL")
    raw_root = Path(data_dir) if data_dir else None
    # 配错的值应该在启动时就炸，而不是等哪天补上 DATA_DIR 后突然把某个上限换成另一个数。
    # 环境校验先于建库，配错优先于缺 DSN。
    queue_max = _env_bytes("MEMHUB_QUEUE_MAX_BYTES", DEFAULT_QUEUE_MAX_BYTES)
    # 目标登记只读 `kb_projects`（规格 §9.2.4）；缺 DSN 在构造时即抛 `KbDsnMissing`。
    owned_kb: PgKnowledgeStore | None = None
    if kb_store is None:
        kb_store = create_runtime_store(schema=schema)
        owned_kb = kb_store
    state = store or build_store()
    queue_store = queue or build_queue(state)
    if content is not None:
        content_store: RawContentStore = content
    elif raw_root is not None:
        content_store = build_content_store(raw_root)
    else:
        # 只用于 dev：没有正文存储时仍推进游标与队列，worker 取不到正文会推迟。
        content_store = NullContentStore()
    owned_closers: list[Callable[[], Awaitable[None]]] = []
    if owned_kb is not None:
        owned_closers.append(owned_kb.aclose)
    if content is None:
        owned_closers.append(content_store.close)
    if store is None:
        from memhub.ingest.postgres import PostgresStore

        if isinstance(state, PostgresStore):
            owned_closers.append(state.close)
    registry = TargetRegistry(kb_store)
    kb_api_url = os.environ.get("MEMHUB_KB_API_URL", DEFAULT_KB_API_URL)
    app = FastAPI(
        title="memhub ingest",
        version="0.1.0",
        lifespan=_ingest_lifespan(owned_closers),
    )
    app.state.store = state
    app.state.queue = queue_store
    app.state.content = content_store

    async def active_project(project: str) -> bool:
        try:
            return await registry.active(project)
        except TargetUnavailable as exc:
            raise _target_lookup_failed() from exc

    async def _audit(device_id: str, project: object, decision: str, reason: str = "") -> None:
        """每次采集一条审计：设备、目标、接受/拒绝、理由、时间；不含内容与 token。

        同步落 `kb_write_audit`（规格 §3.6，`action=ingest`，`result=ok|拒绝理由`）；
        日志只做运维旁路。审计落库失败随原路径上抛，不静默丢记录。
        """
        safe = project if isinstance(project, str) and len(project) <= 64 else ""
        await kb_store.record_write_audit(
            actor=f"device:{device_id}",
            project=safe or None,
            node_id=None,
            action="ingest",
            result="ok" if decision == "accept" else (reason or decision),
        )
        LOGGER.info(
            "ingest decision=%s device=%r project=%r reason=%s at=%s",
            decision,
            device_id,
            safe,
            reason or "-",
            datetime.now(UTC).isoformat(),
        )

    async def check_target(device_id: str, value: object) -> str:
        project = explicit_project(value)
        if project is None:
            if value == PROJECT_AUTO:
                reason = "reserved"
            elif not isinstance(value, str) or not value:
                reason = "missing"
            else:
                reason = "invalid"
            await _audit(device_id, value, "reject", reason)
            raise _target_unavailable(reason)
        try:
            status = await target_status(registry.store, project)
        except TargetUnavailable as exc:
            await _audit(device_id, project, "reject", "registry_unavailable")
            raise _target_lookup_failed() from exc
        if status is not TargetStatus.ACTIVE:
            await _audit(device_id, project, "reject", status.value)
            raise _target_unavailable(status.value)
        return project

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

    async def auth_collector(authorization: str | None, device_id: str) -> None:
        await auth(authorization, device_id)
        # 管理台生产者身份不能从采集接口使用；兼顾 Windows 不区分大小写的路径。
        if collector_device_reserved(device_id):
            raise ApiError(ErrorCode.SCOPE_DENIED, "collector scope denied")

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
        """转发 kb-api 的项目元数据，但只显示当前已登记且活动的项目。"""
        await auth_collector(authorization, device_id)
        upstream = await _kb_api_request(kb_api_url, "GET", "/api/v1/kb/projects")
        if not isinstance(upstream, dict) or not isinstance(upstream.get("items"), list):
            raise _target_lookup_failed()
        items: list[dict[str, Any]] = []
        for item in upstream["items"]:
            if not isinstance(item, dict):
                raise _target_lookup_failed()
            project = explicit_project(item.get("id"))
            if project is not None and await active_project(project):
                items.append(item)
        return _ok({"items": items, "total": len(items), "writable_only": True})

    @app.post("/ingest/raw")
    async def raw(
        body: RawIngestRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await auth_collector(authorization, body.device_id)
        project = await check_target(body.device_id, body.project)
        body.project = project
        for batch_file in body.files:
            if "\x00" in batch_file.content:
                raise ApiError(
                    ErrorCode.UNPARSABLE,
                    "binary content is not accepted",
                    {"path": batch_file.path},
                )
        try:
            replay = await state.check_replay_target(body)
            if replay is not None:
                await _audit(body.device_id, project, "accept", "replay")
                return _ok(replay.model_dump(mode="json"))
            result: IngestResult = await enqueue_batch(
                state,
                queue_store,
                content_store,
                body,
                producer="collector",
                limit=queue_max,
            )
        except BatchTargetConflict as exc:
            await _audit(body.device_id, body.project, "reject", "target_conflict")
            raise _target_unavailable("target_conflict") from exc
        except QuotaExceeded as exc:
            await _audit(body.device_id, project, "reject", "queue_backpressure")
            raise ApiError(
                ErrorCode.QUEUE_BACKPRESSURE,
                "queue quota exceeded",
                {
                    "used_bytes": exc.used,
                    "limit_bytes": exc.limit,
                    "incoming_bytes": exc.incoming,
                },
            ) from exc
        except ContentUnavailable as exc:
            # 正文存储（ClickHouse）不可用：这是服务端临时问题，客户端按背压退避重试。
            await _audit(body.device_id, project, "reject", "content_store_unavailable")
            raise ApiError(
                ErrorCode.QUEUE_BACKPRESSURE,
                "raw content store unavailable",
                {"reason": "content_store_unavailable"},
            ) from exc
        await _audit(body.device_id, project, "accept")
        return _ok(result.model_dump(mode="json"))

    @app.delete("/ingest/source/{source_id}")
    async def purge_source(
        source_id: str,
        device_id: Annotated[str | None, Query()] = None,
        purge: Annotated[str | None, Query()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        """按用户 provision token 清理一个设备源的待提炼队列，不改运行态与知识。

        只删 PG 队列行；正文在 ClickHouse，账号无 DELETE 权限，保留到 180 天 TTL。
        响应显式标记 `content_retained`，不再声称清理了原始字节。
        """
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        if not provision_token or not hmac.compare_digest(
            supplied.encode(), provision_token.encode()
        ):
            raise ApiError(ErrorCode.TOKEN_INVALID, "invalid provision token")
        if (
            purge != "true"
            or device_id is None
            or _DEVICE_ID.fullmatch(device_id) is None
            or _SOURCE_ID.fullmatch(source_id) is None
            or source_id in {".", ".."}
            or collector_device_reserved(device_id)
        ):
            raise ApiError(ErrorCode.BAD_REQUEST, "invalid purge target")

        counts = {"queued": 0, "processing": 0, "processed": 0, "pending_review": 0}
        try:
            raw_counts = await queue_store.purge_source(device_id, source_id)
        except ContentUnavailable as exc:
            raise ApiError(
                ErrorCode.QUEUE_BACKPRESSURE,
                "queue unavailable",
                {"reason": "queue_unavailable"},
            ) from exc
        for status in counts:
            counts[status] = raw_counts.get(status, 0)

        await kb_store.record_write_audit(
            actor="provision",
            project=None,
            node_id=None,
            action="ingest_purge",
            result="ok",
        )
        return _ok(
            {
                "device_id": device_id,
                "source_id": source_id,
                "purged": counts,
                "content_retained": True,
                "content_retention": "clickhouse_ttl_180d",
            }
        )

    # -- 内部接口：管理台上传（kb-api 调用，MEMHUB_INTERNAL_TOKEN 鉴权） --------

    async def internal_auth(authorization: str | None) -> None:
        if not internal_token:
            raise ApiError(ErrorCode.INTERNAL, "internal api disabled")
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        if not hmac.compare_digest(supplied.encode(), internal_token.encode()):
            raise ApiError(ErrorCode.TOKEN_INVALID, "invalid internal token")

    @app.post("/internal/enqueue")
    async def internal_enqueue(
        body: IngestRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        """管理台上传批次入队：与采集同一套正文存储与队列，只是没有设备 token。"""
        await internal_auth(authorization)
        project = explicit_project(body.project)
        if project is None:
            raise ApiError(ErrorCode.BAD_REQUEST, "project required")
        # 目标必须是已登记且活动的知识库；拼错的库名不能凭空建出空库。
        await check_target(body.device_id, project)
        replay = await state.check_replay_target(body)
        if replay is not None:
            return _ok(replay.model_dump(mode="json"))
        try:
            result = await enqueue_batch(
                state,
                queue_store,
                content_store,
                body,
                producer="console",
                limit=queue_max,
            )
        except BatchTargetConflict as exc:
            raise ApiError(ErrorCode.BAD_REQUEST, "queue target conflict") from exc
        except QuotaExceeded as exc:
            raise ApiError(
                ErrorCode.KB_QUEUE_FULL,
                "queue quota exceeded",
                {
                    "used_bytes": exc.used,
                    "limit_bytes": exc.limit,
                    "incoming_bytes": exc.incoming,
                },
            ) from exc
        except ContentUnavailable as exc:
            raise ApiError(
                ErrorCode.QUEUE_BACKPRESSURE,
                "raw content store unavailable",
                {"reason": "content_store_unavailable"},
            ) from exc
        return _ok(result.model_dump(mode="json"))

    @app.get("/internal/queue/{batch_id}")
    async def internal_queue(
        batch_id: str,
        project: Annotated[str | None, Query()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        """批次提炼进度；kb-api 据此展示上传状态。

        `project` 可省略：管理台上传的 batch_id 是 uuid，可唯一反查所属库；
        采集批次可能出现同名 batch_id，省略时按歧义处理（404）。
        """
        await internal_auth(authorization)
        resolved = project
        if resolved is None:
            resolved = await queue_store.batch_project(batch_id)
        elif explicit_project(resolved) is None:
            raise ApiError(ErrorCode.BAD_REQUEST, "invalid project")
        if resolved is None or explicit_project(resolved) is None:
            raise ApiError(ErrorCode.KB_NOT_FOUND, "batch not found")
        progress = await queue_store.batch_progress(resolved, batch_id)
        if progress is None:
            raise ApiError(ErrorCode.KB_NOT_FOUND, "batch not found")
        items = await queue_store.batch_items(resolved, batch_id)
        return _ok(_progress_payload(resolved, progress, items))

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
