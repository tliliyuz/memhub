"""知识库管理 API（kb-api，全异步 IO）。

本地单用户管理台的后端：列表/搜索/详情/新增/编辑/废弃/归档删除/边编辑/审计，
外加知识库上传。写操作落 PG 真源 `kb_*` 表（见 `memhub.kb.pgstore`）。
启动时强制要求 `MEMHUB_KB_DB_URL`，没有文件存储退路（规格 §9.2.4）。

上传（`/api/v1/kb/uploads`）把文件直接送进提炼队列：落盘走 `memhub.queue.rawstore`，
与 `/ingest/raw` 共用同一套 raw_store 布局与配额，不经过采集协议（见 `memhub.kb.uploads`）。
未配置 `MEMHUB_DATA_DIR` 时上传接口返回 503，其余接口不受影响。

只绑回环地址、无鉴权：管理台与 worker、collector 跑在同一台机器上，
公网入口（如果将来有）由 nginx + oauth2-proxy 负责，不在本层做会话。

启动：

    memhub kb --web-dist web/dist
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from anyio import Path as AsyncPath
from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from memhub.contract import Edge, EntityKind, ErrorCode, Kind, Predicate, QuestionStatus, Tier
from memhub.kb import catalog, manage, query, trace_query
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KB_SCHEMA, create_runtime_store
from memhub.kb.target_access import TargetUnavailable, registered_active
from memhub.kb.uploads import KbUploads, UploadInvalid, UploadQueueFull
from memhub.mcp.auth import load_grants
from memhub.mcp.http import McpEndpoint
from memhub.queue.rawstore import RawStoreQuota

DEFAULT_QUEUE_MAX_BYTES = 1024**3


def _env_bytes(name: str, default: int) -> int:
    """读字节数配置；非法值直接启动失败，而不是悄悄退回默认值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是整数字节数: {raw!r}") from exc
    if value <= 0:
        raise SystemExit(f"{name} 必须为正数: {value}")
    return value


class NodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    project: str = "memhub"
    tier: Tier = Tier.CANONICAL
    tags: list[str] = Field(default_factory=list)
    entity_kind: EntityKind | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: QuestionStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    slug: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    actor: str = "ui"

    def to_draft(self) -> manage.NodeDraft:
        return manage.NodeDraft(
            kind=self.kind,
            title=self.title,
            body=self.body,
            project=self.project,
            tier=self.tier,
            tags=self.tags,
            entity_kind=self.entity_kind,
            confidence=self.confidence,
            status=self.status,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            occurred_at=self.occurred_at,
            decided_at=self.decided_at,
            slug=self.slug,
            supersedes=self.supersedes,
            actor=self.actor,
        )


class NodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    tags: list[str] | None = None
    tier: Tier | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: QuestionStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    superseded_by: str | None = None
    actor: str = "ui"

    def to_patch(self) -> manage.NodePatch:
        return manage.NodePatch(
            title=self.title,
            body=self.body,
            tags=self.tags,
            tier=self.tier,
            confidence=self.confidence,
            status=self.status,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            occurred_at=self.occurred_at,
            decided_at=self.decided_at,
            superseded_by=self.superseded_by,
            actor=self.actor,
        )


class DeprecateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    superseded_by: str = Field(min_length=1)
    reason: str = ""
    actor: str = "ui"


class EdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicate: Predicate
    target: str = Field(min_length=1)


class EdgesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[EdgeInput] = Field(default_factory=list)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trash: str = Field(min_length=1)


class RestoreProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archive_id: str = Field(min_length=1, max_length=32)


class KbCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    description: str = ""


class KbUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None


class KnowledgeApi:
    """API 运行时状态：真源存储。"""

    def __init__(self, store: PgKnowledgeStore) -> None:
        self.store = store


def _error_response(exc: manage.ManageError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"code": int(exc.code), "message": exc.message, "data": exc.data},
    )


def create_app(
    *,
    store: PgKnowledgeStore | None = None,
    schema: str | None = KB_SCHEMA,
) -> FastAPI:
    """组装 kb-api；默认按 `MEMHUB_KB_DB_URL` 强制构造 PG 存储（规格 §9.2.4）。

    `store` 与 `schema` 仅供测试注入独立 schema；生产入口不留文件存储退路，
    `search_path` 固定为 `kb`。
    """
    web_dist_raw = os.environ.get("MEMHUB_KB_WEB_DIST", "")
    web_dist = Path(web_dist_raw) if web_dist_raw else None
    owned: PgKnowledgeStore | None = None
    if store is None:
        owned = create_runtime_store(schema=schema)
        store = owned
    api = KnowledgeApi(store)
    data_dir_raw = os.environ.get("MEMHUB_DATA_DIR", "").strip()
    uploads: KbUploads | None = None
    if data_dir_raw:
        data_dir = Path(data_dir_raw).expanduser()
        queue_max = _env_bytes("MEMHUB_QUEUE_MAX_BYTES", DEFAULT_QUEUE_MAX_BYTES)
        uploads = KbUploads(data_dir, RawStoreQuota(data_dir / "raw_store", queue_max))

    mcp = McpEndpoint(api.store, load_grants(os.environ.get("MEMHUB_MCP_GRANTS", "")))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            async with mcp.lifespan():
                yield
        finally:
            if owned is not None:
                await owned.aclose()

    app = FastAPI(title="memhub kb-api", version="0.1.0", lifespan=lifespan)
    app.state.kb = api
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(mcp.wrap)

    @app.exception_handler(manage.ManageError)
    async def on_manage_error(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, manage.ManageError):
            raise exc
        return _error_response(exc)

    @app.exception_handler(query.NotFound)
    async def on_query_not_found(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, query.NotFound):
            raise exc
        return JSONResponse(
            status_code=404,
            content={"code": 1011, "message": str(exc), "data": {}},
        )

    @app.exception_handler(query.QueryError)
    async def on_query_error(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, query.QueryError):
            raise exc
        return JSONResponse(
            status_code=422,
            content={"code": int(ErrorCode.KB_INVALID), "message": str(exc), "data": {}},
        )

    @app.exception_handler(UploadInvalid)
    async def on_upload_invalid(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, UploadInvalid):
            raise exc
        if exc.status >= 500:
            code = int(ErrorCode.INTERNAL)
        elif exc.status == 404:
            code = int(ErrorCode.KB_NOT_FOUND)
        else:
            code = int(ErrorCode.KB_INVALID)
        return JSONResponse(
            status_code=exc.status,
            content={"code": code, "message": exc.message, "data": exc.data},
        )

    @app.exception_handler(UploadQueueFull)
    async def on_upload_queue_full(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, UploadQueueFull):
            raise exc
        return JSONResponse(
            status_code=503,
            content={
                "code": int(ErrorCode.KB_QUEUE_FULL),
                "message": "提炼队列已满，请稍后重试",
                "data": {"used": exc.used, "limit": exc.limit, "incoming": exc.incoming},
            },
        )

    # ---- 健康与统计 ----

    @app.get("/healthz")
    @app.get("/api/v1/kb/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "store": "pg",
            "nodes": len(await api.store.list_ids()),
        }

    @app.get("/api/v1/kb/stats")
    async def stats() -> dict[str, Any]:
        return await manage.stats(api.store)

    # ---- 知识库（project）----

    @app.get("/api/v1/kb/projects")
    async def list_projects() -> dict[str, Any]:
        return await catalog.list_kbs(api.store)

    @app.post("/api/v1/kb/projects", status_code=201)
    async def create_project(body: KbCreate) -> dict[str, Any]:
        return await catalog.create_kb(
            api.store, kb_id=body.id, name=body.name, description=body.description
        )

    @app.patch("/api/v1/kb/projects/{project}")
    async def update_project(project: str, body: KbUpdate) -> dict[str, Any]:
        return await catalog.update_kb(
            api.store, project, name=body.name, description=body.description
        )

    @app.delete("/api/v1/kb/projects/{project}")
    async def delete_project(project: str, actor: str = "ui") -> dict[str, Any]:
        return await catalog.delete_kb(api.store, project, actor=actor)

    @app.get("/api/v1/kb/graph")
    async def knowledge_graph(project: str = Query(min_length=1)) -> dict[str, Any]:
        return await catalog.graph(api.store, project)

    # ---- 节点 ----

    @app.get("/api/v1/kb/nodes")
    async def list_nodes(
        project: str | None = None,
        kind: str | None = None,
        tier: str | None = None,
        q: str | None = None,
        tag: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return await manage.list_nodes(
            api.store,
            project=project,
            kind=kind,
            tier=tier,
            q=q,
            tag=tag,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/v1/kb/nodes", status_code=201)
    async def create_node(body: NodeCreate) -> dict[str, Any]:
        return await manage.create_node(api.store, body.to_draft())

    @app.get("/api/v1/kb/nodes/{node_id:path}")
    async def get_node(node_id: str) -> dict[str, Any]:
        return await manage.get_node(api.store, node_id)

    # 注意顺序：`{node_id:path}` 是贪婪匹配，`/edges` 必须先注册，
    # 否则 PUT /nodes/a/b/edges 会被当成 id="a/b/edges" 的节点更新。
    @app.put("/api/v1/kb/nodes/{node_id:path}/edges")
    async def replace_edges(node_id: str, body: EdgesUpdate) -> dict[str, Any]:
        edges = [
            Edge(source=node_id, predicate=item.predicate, target=item.target)
            for item in body.edges
        ]
        return await manage.replace_out_edges(api.store, node_id, edges)

    @app.put("/api/v1/kb/nodes/{node_id:path}")
    async def update_node(node_id: str, body: NodeUpdate) -> dict[str, Any]:
        return await manage.update_node(
            api.store, node_id, expected_revision=body.expected_revision, patch=body.to_patch()
        )

    @app.post("/api/v1/kb/nodes/{node_id:path}/deprecate")
    async def deprecate_node(node_id: str, body: DeprecateRequest) -> dict[str, Any]:
        return await manage.deprecate_node(
            api.store,
            node_id,
            superseded_by=body.superseded_by,
            reason=body.reason,
            actor=body.actor,
        )

    @app.delete("/api/v1/kb/nodes/{node_id:path}")
    async def delete_node(
        node_id: str,
        revision: str = Query(min_length=1),
        reason: str = "",
        actor: str = "ui",
    ) -> dict[str, Any]:
        return await manage.delete_node(
            api.store, node_id, expected_revision=revision, reason=reason, actor=actor
        )

    # ---- 回收站 ----

    @app.get("/api/v1/kb/trash")
    async def list_trash(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        project: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        return await manage.list_trash(api.store, limit=limit, offset=offset, project=project, q=q)

    @app.post("/api/v1/kb/trash/restore")
    async def restore_trash(body: RestoreRequest) -> dict[str, Any]:
        return await manage.restore_node(api.store, body.trash)

    @app.get("/api/v1/kb/trash/projects")
    async def list_project_trash() -> dict[str, Any]:
        return await catalog.list_archives(api.store)

    @app.post("/api/v1/kb/trash/projects/restore")
    async def restore_project_trash(body: RestoreProjectRequest) -> dict[str, Any]:
        return await catalog.restore_kb(api.store, body.archive_id)

    # ---- 当前登录用户（nginx 经 oauth2-proxy 注入 X-Memhub-User）----

    @app.get("/api/v1/kb/me")
    async def me(request: Request, response: Response) -> dict[str, Any]:
        # 生产环境由网关覆盖此头；本地直连时没有登录身份。
        response.headers["Cache-Control"] = "no-store"
        user = request.headers.get("x-memhub-user", "").strip()
        return {
            "authenticated": bool(user),
            "user": user or None,
            "avatar_url": f"https://github.com/{quote(user, safe='')}.png?size=64"
            if user
            else None,
        }

    # ---- 上传（送进提炼队列）----

    def _uploads_unavailable() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": int(ErrorCode.INTERNAL),
                "message": "未配置 MEMHUB_DATA_DIR，上传不可用",
                "data": {},
            },
        )

    @app.post("/api/v1/kb/uploads", status_code=201, response_model=None)
    async def create_upload(
        project: Annotated[str, Form(min_length=1)],
        files: Annotated[list[UploadFile], File(...)],
    ) -> dict[str, Any] | JSONResponse:
        if uploads is None:
            return _uploads_unavailable()
        try:
            return await uploads.accept(
                project,
                files,
                project_exists=lambda kb_id: registered_active(api.store, kb_id),
            )
        except TargetUnavailable as exc:
            raise UploadInvalid("暂无法验证知识库目标，请稍后重试", status=503) from exc

    @app.get("/api/v1/kb/uploads/{batch_id}", response_model=None)
    async def upload_status(batch_id: str) -> dict[str, Any] | JSONResponse:
        if uploads is None:
            return _uploads_unavailable()
        return await uploads.status(batch_id)

    # ---- 检索与审计 ----

    @app.get("/api/v1/kb/search")
    async def search(
        q: str,
        project: str | None = None,
        kinds: str | None = None,
        tier: str = "canonical",
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        kind_list = [item for item in (kinds or "").split(",") if item] or None
        return await query.search(
            api.store, q, project=project, kinds=kind_list, tier=tier, limit=limit
        )

    @app.get("/api/v1/kb/audit")
    async def audit(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return await query.audit_list(api.store, limit=limit, offset=offset)

    # ---- MCP 调用轨迹（ADR-0015） ----

    def _traces_unavailable() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": int(ErrorCode.INTERNAL),
                "message": "调用轨迹只在 PG 存储上可用",
                "data": {},
            },
        )

    @app.get("/api/v1/kb/mcp-traces", response_model=None)
    async def list_mcp_traces(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        event: str = Query(default="call", pattern="^(call|list_tools|initialize)$"),
        tool: str | None = None,
        status: str | None = None,
        credential: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any] | JSONResponse:
        if not isinstance(api.store, PgKnowledgeStore):
            return _traces_unavailable()
        return await trace_query.mcp_traces(
            api.store,
            limit=limit,
            offset=offset,
            event=event,
            tool=tool,
            status=status,
            credential=credential,
            since=since,
            until=until,
        )

    @app.get("/api/v1/kb/mcp-traces/summary", response_model=None)
    async def mcp_traces_summary(
        days: int = Query(default=7, ge=1, le=30),
    ) -> dict[str, Any] | JSONResponse:
        if not isinstance(api.store, PgKnowledgeStore):
            return _traces_unavailable()
        return await trace_query.mcp_traces_summary(api.store, days=days)

    # ---- 静态前端（打包产物）----

    index = web_dist / "index.html" if web_dist is not None else None
    if web_dist is not None:
        # `check_dir=False`：是否构建由请求期判断，启动期不做同步 stat。
        app.mount(
            "/assets",
            StaticFiles(directory=web_dist / "assets", check_dir=False),
            name="assets",
        )

        @app.get("/{path:path}", response_model=None)
        async def spa(path: str) -> FileResponse | JSONResponse:
            if path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"code": 1011, "message": "未知接口", "data": {"path": path}},
                )
            if index is None or not await AsyncPath(index).is_file():
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": 2002,
                        "message": "前端未构建",
                        "data": {"dist": str(web_dist)},
                    },
                )
            candidate = web_dist / path
            if (
                path
                and await AsyncPath(candidate).is_file()
                and web_dist in Path(await AsyncPath(candidate).resolve()).parents
            ):
                return FileResponse(candidate)
            return FileResponse(index)

    return app
