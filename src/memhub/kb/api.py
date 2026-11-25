"""知识库管理 API（kb-api，全异步 IO）。

本地单用户管理台的后端：列表/搜索/详情/新增/编辑/废弃/归档删除/边编辑/审计，
外加投影重建与知识库上传。写操作落 PG 真源 `kb_*` 表（见 `memhub.kb.pgstore`），
写完可选自动重建 `kg.json` 投影。启动时强制要求 `MEMHUB_KB_DB_URL`，没有文件
存储退路（规格 §9.2.4）。

上传（`/api/v1/kb/uploads`）把文件直接送进提炼队列：落盘走 `memhub.queue.rawstore`，
与 `/ingest/raw` 共用同一套 raw_store 布局与配额，不经过采集协议（见 `memhub.kb.uploads`）。
未配置 `MEMHUB_DATA_DIR` 时上传接口返回 503，其余接口不受影响。

只绑回环地址、无鉴权：管理台与 worker、collector 跑在同一台机器上，
公网入口（如果将来有）由 nginx + oauth2-proxy 负责，不在本层做会话。

启动：

    memhub kb --graph-out kb/kg.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import anyio
from anyio import Path as AsyncPath
from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from memhub.contract import Edge, EntityKind, ErrorCode, Kind, Predicate, QuestionStatus, Tier
from memhub.kb import archive, catalog, manage, proc, query, trace_query
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.projection import save_projection
from memhub.kb.session import KB_SCHEMA, create_runtime_store
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetUnavailable, registered_active
from memhub.kb.uploads import KbUploads, UploadInvalid, UploadQueueFull
from memhub.mcp.auth import load_grants
from memhub.mcp.http import McpEndpoint
from memhub.queue.rawstore import RawStoreQuota

DEFAULT_GRAPH = "kb/kg.json"
REBUILD_DEBOUNCE_SECONDS = 1.5
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


_log = logging.getLogger(__name__)


class NodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    project: str = "memhub"
    tier: Tier = Tier.CANDIDATE
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


class _RebuildState:
    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.due_at: float | None = None
        self.running = False
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.nodes = 0
        self.edges = 0
        self.unresolved = 0


class KnowledgeApi:
    """API 运行时状态：真源存储、投影输出、防抖重建。"""

    def __init__(
        self,
        store: KnowledgeStore | PgKnowledgeStore,
        graph_out: Path,
        *,
        auto_rebuild: bool = True,
        on_rebuilt: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.store = store
        self.graph_out = graph_out
        self.auto_rebuild = auto_rebuild
        self.on_rebuilt = on_rebuilt
        self.state = _RebuildState()

    # ---- 投影 ----

    async def rebuild_now(self) -> dict[str, Any]:
        self.state.running = True
        self.state.started_at = datetime.now(UTC).isoformat()
        self.state.error = None
        try:
            report = await save_projection(self.store, self.graph_out, clear_archive_dirty=True)
            self.state.nodes = report.nodes
            self.state.edges = report.edges
            self.state.unresolved = len(report.unresolved)
            self.state.error = None
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.state.running = False
            self.state.finished_at = datetime.now(UTC).isoformat()
        if self.on_rebuilt is not None:
            await self.on_rebuilt()
        return await self.rebuild_status()

    async def _graph_counts(self) -> tuple[int, int] | None:
        """直接数现有投影文件：冷启动（本进程还没重建过）时也能报出真实规模。"""
        if not await AsyncPath(self.graph_out).is_file():
            return None
        try:
            data = json.loads(await AsyncPath(self.graph_out).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        nodes = data.get("nodes") or []
        edges = data.get("edges") or data.get("links") or []
        return len(nodes), len(edges)

    async def rebuild_status(self) -> dict[str, Any]:
        state = self.state
        graph_mtime = None
        if await AsyncPath(self.graph_out).is_file():
            mtime = (await AsyncPath(self.graph_out).stat()).st_mtime
            graph_mtime = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        counts = await self._graph_counts()
        nodes, edges = counts if counts is not None else (state.nodes, state.edges)
        return {
            "running": state.running,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "error": state.error,
            "nodes": nodes,
            "edges": edges,
            "unresolved_edges": state.unresolved,
            "graph": str(self.graph_out),
            "graph_mtime": graph_mtime,
            "stale": await self.projection_stale(),
        }

    async def projection_stale(self) -> bool:
        """投影是否落后于真源。

        文件真源靠 mtime 与归档标记；PG 真源没有文件 mtime，改比 `latest_write`。
        """
        if not isinstance(self.store, PgKnowledgeStore) and await archive.projection_dirty(
            self.store.root
        ):
            return True
        if not await AsyncPath(self.graph_out).is_file():
            if isinstance(self.store, PgKnowledgeStore):
                return True
            return await AsyncPath(self.store.root).is_dir()
        graph_mtime = (await AsyncPath(self.graph_out).stat()).st_mtime
        if isinstance(self.store, PgKnowledgeStore):
            latest = await self.store.latest_write()
            return latest is not None and latest.timestamp() > graph_mtime
        for node_id in await self.store.list_ids():
            try:
                if (await AsyncPath(self.store.path_for(node_id)).stat()).st_mtime > graph_mtime:
                    return True
            except OSError:
                continue
        async for path in AsyncPath(self.store.root).rglob("_edges.jsonl"):
            try:
                if (await path.stat()).st_mtime > graph_mtime:
                    return True
            except OSError:
                continue
        return False

    def schedule_rebuild(self) -> None:
        """写操作后的防抖重建：连续保存只重建一次。"""
        if not self.auto_rebuild:
            return
        self.state.due_at = time.monotonic() + REBUILD_DEBOUNCE_SECONDS
        if self.state.task is not None and not self.state.task.done():
            return
        self.state.task = asyncio.get_running_loop().create_task(self._debounce_loop())

    async def _debounce_loop(self) -> None:
        while True:
            due_at = self.state.due_at
            if due_at is None:
                return
            wait = due_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(min(wait, 0.5))
                continue
            self.state.due_at = None
            try:
                await self.rebuild_now()
            except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常抛给请求
                # 失败原因已经写进 state.error 供 UI 展示；这里只留一条服务端日志。
                _log.warning("投影重建失败: %s", exc)


def _error_response(exc: manage.ManageError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"code": int(exc.code), "message": exc.message, "data": exc.data},
    )


def create_app(
    *,
    store: KnowledgeStore | PgKnowledgeStore | None = None,
    schema: str | None = KB_SCHEMA,
) -> FastAPI:
    """组装 kb-api；默认按 `MEMHUB_KB_DB_URL` 强制构造 PG 存储（规格 §9.2.4）。

    `store` 与 `schema` 仅供测试注入独立 schema；生产入口不留文件存储退路，
    `search_path` 固定为 `kb`。
    """
    graph_out = Path(os.environ.get("MEMHUB_KB_GRAPH", DEFAULT_GRAPH))
    web_dist_raw = os.environ.get("MEMHUB_KB_WEB_DIST", "")
    web_dist = Path(web_dist_raw) if web_dist_raw else None
    auto_rebuild = os.environ.get("MEMHUB_KB_AUTO_REBUILD", "1") not in {"0", "off", "false"}
    graph_restarter = _GraphRestarter.from_env()
    owned: PgKnowledgeStore | None = None
    if store is None:
        owned = create_runtime_store(schema=schema)
        store = owned
    api = KnowledgeApi(
        store,
        graph_out,
        auto_rebuild=auto_rebuild,
        on_rebuilt=graph_restarter.restart if graph_restarter else None,
    )
    data_dir_raw = os.environ.get("MEMHUB_DATA_DIR", "").strip()
    uploads: KbUploads | None = None
    if data_dir_raw:
        data_dir = Path(data_dir_raw).expanduser()
        queue_max = _env_bytes("MEMHUB_QUEUE_MAX_BYTES", DEFAULT_QUEUE_MAX_BYTES)
        uploads = KbUploads(data_dir, RawStoreQuota(data_dir / "raw_store", queue_max))

    mcp = McpEndpoint(api.store, load_grants(os.environ.get("MEMHUB_MCP_GRANTS", "")))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if graph_restarter is not None and await AsyncPath(graph_out).is_file():
            await graph_restarter.start()
        if not isinstance(api.store, PgKnowledgeStore) and await archive.projection_dirty(
            api.store.root
        ):
            api.schedule_rebuild()
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

    async def _write(action: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        result = await action
        api.schedule_rebuild()
        return result

    # ---- 健康与统计 ----

    @app.get("/healthz")
    @app.get("/api/v1/kb/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "store": "pg" if isinstance(api.store, PgKnowledgeStore) else "files",
            "nodes": len(await api.store.list_ids()),
            "projection": await api.rebuild_status(),
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
        return await _write(catalog.delete_kb(api.store, project, actor=actor))

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
        return await _write(manage.create_node(api.store, body.to_draft()))

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
        return await _write(manage.replace_out_edges(api.store, node_id, edges))

    @app.put("/api/v1/kb/nodes/{node_id:path}")
    async def update_node(node_id: str, body: NodeUpdate) -> dict[str, Any]:
        return await _write(
            manage.update_node(
                api.store, node_id, expected_revision=body.expected_revision, patch=body.to_patch()
            )
        )

    @app.post("/api/v1/kb/nodes/{node_id:path}/deprecate")
    async def deprecate_node(node_id: str, body: DeprecateRequest) -> dict[str, Any]:
        return await _write(
            manage.deprecate_node(
                api.store,
                node_id,
                superseded_by=body.superseded_by,
                reason=body.reason,
                actor=body.actor,
            )
        )

    @app.delete("/api/v1/kb/nodes/{node_id:path}")
    async def delete_node(
        node_id: str,
        revision: str = Query(min_length=1),
        reason: str = "",
        actor: str = "ui",
    ) -> dict[str, Any]:
        return await _write(
            manage.delete_node(
                api.store, node_id, expected_revision=revision, reason=reason, actor=actor
            )
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
        return await _write(manage.restore_node(api.store, body.trash))

    @app.get("/api/v1/kb/trash/projects")
    async def list_project_trash() -> dict[str, Any]:
        return await catalog.list_archives(api.store)

    @app.post("/api/v1/kb/trash/projects/restore")
    async def restore_project_trash(body: RestoreProjectRequest) -> dict[str, Any]:
        return await _write(catalog.restore_kb(api.store, body.archive_id))

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
        tier: str = "all",
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

    # ---- MCP 调用轨迹（ADR-0014） ----

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

    # ---- 投影 ----

    @app.get("/api/v1/kb/rebuild")
    @app.get("/api/v1/kb/projection")
    async def rebuild_status() -> dict[str, Any]:
        return await api.rebuild_status()

    @app.post("/api/v1/kb/rebuild", response_model=None)
    async def rebuild() -> Any:
        try:
            return await api.rebuild_now()
        except Exception as exc:  # noqa: BLE001 - 返回 500 + 原因，让 UI 展示
            return JSONResponse(
                status_code=500,
                content={
                    "code": 2001,
                    "message": f"投影重建失败: {type(exc).__name__}: {exc}",
                    "data": await api.rebuild_status(),
                },
            )

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


class _GraphRestarter:
    """可选：由 kb-api 拉起 explorer 子进程，投影重建后自动重启它。

    explorer 只在启动时读一次 kg.json，不重启就看不到新图谱；本地形态下
    让 kb-api 托管它是最省心的做法。未设置 `MEMHUB_KB_GRAPH_PORT` 时本类不生效。
    """

    def __init__(self, graph: Path, port: int) -> None:
        self.graph = graph
        self.port = port
        self.process: Any = None
        self.lock = anyio.Lock()

    @classmethod
    def from_env(cls) -> _GraphRestarter | None:
        port = os.environ.get("MEMHUB_KB_GRAPH_PORT", "").strip()
        if not port:
            return None
        graph = Path(os.environ.get("MEMHUB_KB_GRAPH", DEFAULT_GRAPH))
        return cls(graph, int(port))

    async def start(self) -> None:
        async with self.lock:
            await self._spawn_locked()

    async def _spawn_locked(self) -> None:
        if self.process is not None and proc.exit_code(self.process) is None:
            return
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
        self.process = await proc.spawn(
            [
                sys.executable,
                "-m",
                "semantica.explorer",
                "--graph",
                str(self.graph),
                "--port",
                str(self.port),
                "--host",
                "127.0.0.1",
                "--no-browser",
            ],
            env=env,
        )

    async def restart(self) -> None:
        async with self.lock:
            process = self.process
            self.process = None
            if process is not None and proc.exit_code(process) is None:
                proc.terminate(process)
                with anyio.move_on_after(5):
                    while proc.exit_code(process) is None:
                        await anyio.sleep(0.1)
                if proc.exit_code(process) is None:
                    proc.kill(process)
            await self._spawn_locked()

    async def stop(self) -> None:
        async with self.lock:
            process = self.process
            self.process = None
            proc.terminate(process)
