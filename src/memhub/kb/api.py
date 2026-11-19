"""知识库管理 API（kb-api）。

本地单用户管理台的后端：列表/搜索/详情/新增/编辑/废弃/归档删除/边编辑/审计，
外加投影重建。所有写操作落到 markdown 真源（见 `memhub.kb.manage`），
写完可选自动重建 `kg.json` 投影。

只绑回环地址、无鉴权：管理台与 worker、collector 跑在同一台机器上，
公网入口（如果将来有）由 nginx + oauth2-proxy 负责，不在本层做会话。

启动：

    memhub kb --knowledge-dir ./knowledge --graph-out kb/kg.json
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from memhub.contract import Edge, EntityKind, Kind, Predicate, QuestionStatus, Tier
from memhub.kb import manage, query
from memhub.kb.projection import save_projection
from memhub.kb.store import KnowledgeStore

DEFAULT_GRAPH = "kb/kg.json"
REBUILD_DEBOUNCE_SECONDS = 1.5

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


class _RebuildState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.due_at: float | None = None
        self.running = False
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.nodes = 0
        self.edges = 0
        self.unresolved = 0


class KnowledgeApi:
    """API 运行时状态：真源目录、投影输出、防抖重建。"""

    def __init__(
        self,
        knowledge_dir: Path,
        graph_out: Path,
        *,
        auto_rebuild: bool = True,
        on_rebuilt: Callable[[], None] | None = None,
    ) -> None:
        self.store = KnowledgeStore(knowledge_dir)
        self.graph_out = graph_out
        self.auto_rebuild = auto_rebuild
        self.on_rebuilt = on_rebuilt
        self.state = _RebuildState()

    # ---- 投影 ----

    def rebuild_now(self) -> dict[str, Any]:
        with self.state.lock:
            self.state.running = True
            self.state.started_at = datetime.now(UTC).isoformat()
            self.state.error = None
        try:
            report = save_projection(self.store, self.graph_out)
            with self.state.lock:
                self.state.nodes = report.nodes
                self.state.edges = report.edges
                self.state.unresolved = len(report.unresolved)
                self.state.error = None
        except Exception as exc:
            with self.state.lock:
                self.state.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            with self.state.lock:
                self.state.running = False
                self.state.finished_at = datetime.now(UTC).isoformat()
        if self.on_rebuilt is not None:
            self.on_rebuilt()
        return self.rebuild_status()

    def _graph_counts(self) -> tuple[int, int] | None:
        """直接数现有投影文件：冷启动（本进程还没重建过）时也能报出真实规模。"""
        if not self.graph_out.is_file():
            return None
        try:
            data = json.loads(self.graph_out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        nodes = data.get("nodes") or []
        edges = data.get("edges") or data.get("links") or []
        return len(nodes), len(edges)

    def rebuild_status(self) -> dict[str, Any]:
        state = self.state
        graph_mtime = None
        if self.graph_out.is_file():
            graph_mtime = datetime.fromtimestamp(self.graph_out.stat().st_mtime, tz=UTC).isoformat()
        counts = self._graph_counts()
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
            "stale": self.projection_stale(),
        }

    def projection_stale(self) -> bool:
        """真源比投影新（或有节点但还没有投影）即为过期。"""
        if not self.graph_out.is_file():
            return self.store.root.is_dir()
        graph_mtime = self.graph_out.stat().st_mtime
        for node_id in self.store.list_ids():
            try:
                if self.store.path_for(node_id).stat().st_mtime > graph_mtime:
                    return True
            except OSError:
                continue
        for path in self.store.root.rglob("_edges.jsonl"):
            try:
                if path.stat().st_mtime > graph_mtime:
                    return True
            except OSError:
                continue
        return False

    def schedule_rebuild(self) -> None:
        """写操作后的防抖重建：连续保存只重建一次。"""
        if not self.auto_rebuild:
            return
        with self.state.lock:
            self.state.due_at = time.monotonic() + REBUILD_DEBOUNCE_SECONDS
            if self.state.thread is not None and self.state.thread.is_alive():
                return
            thread = threading.Thread(target=self._debounce_loop, daemon=True)
            self.state.thread = thread
        thread.start()

    def _debounce_loop(self) -> None:
        while True:
            with self.state.lock:
                due_at = self.state.due_at
            if due_at is None:
                with self.state.lock:
                    self.state.thread = None
                return
            wait = due_at - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 0.5))
                continue
            with self.state.lock:
                self.state.due_at = None
            try:
                self.rebuild_now()
            except Exception as exc:  # noqa: BLE001 - 后台线程不能把异常抛给请求
                # 失败原因已经写进 state.error 供 UI 展示；这里只留一条服务端日志。
                _log.warning("投影重建失败: %s", exc)
            with self.state.lock:
                if self.state.due_at is None:
                    self.state.thread = None
                    return


def _error_response(exc: manage.ManageError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"code": int(exc.code), "message": exc.message, "data": exc.data},
    )


def create_app() -> FastAPI:
    knowledge_dir = Path(os.environ.get("MEMHUB_KNOWLEDGE_DIR", "./knowledge"))
    graph_out = Path(os.environ.get("MEMHUB_KB_GRAPH", DEFAULT_GRAPH))
    web_dist_raw = os.environ.get("MEMHUB_KB_WEB_DIST", "")
    web_dist = Path(web_dist_raw) if web_dist_raw else None
    auto_rebuild = os.environ.get("MEMHUB_KB_AUTO_REBUILD", "1") not in {"0", "off", "false"}
    graph_restarter = _GraphRestarter.from_env()
    api = KnowledgeApi(
        knowledge_dir,
        graph_out,
        auto_rebuild=auto_rebuild,
        on_rebuilt=graph_restarter.restart if graph_restarter else None,
    )

    app = FastAPI(title="memhub kb-api", version="0.1.0")
    app.state.kb = api
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    def _write(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        result = action()
        api.schedule_rebuild()
        return result

    # ---- 健康与统计 ----

    @app.get("/healthz")
    @app.get("/api/v1/kb/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "knowledge_dir": str(api.store.root),
            "nodes": len(api.store.list_ids()),
            "projection": api.rebuild_status(),
        }

    @app.get("/api/v1/kb/stats")
    def stats() -> dict[str, Any]:
        return manage.stats(api.store)

    # ---- 节点 ----

    @app.get("/api/v1/kb/nodes")
    def list_nodes(
        project: str | None = None,
        kind: str | None = None,
        tier: str | None = None,
        q: str | None = None,
        tag: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return manage.list_nodes(
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
    def create_node(body: NodeCreate) -> dict[str, Any]:
        return _write(lambda: manage.create_node(api.store, body.to_draft()))

    @app.get("/api/v1/kb/nodes/{node_id:path}")
    def get_node(node_id: str) -> dict[str, Any]:
        return manage.get_node(api.store, node_id)

    # 注意顺序：`{node_id:path}` 是贪婪匹配，`/edges` 必须先注册，
    # 否则 PUT /nodes/a/b/edges 会被当成 id="a/b/edges" 的节点更新。
    @app.put("/api/v1/kb/nodes/{node_id:path}/edges")
    def replace_edges(node_id: str, body: EdgesUpdate) -> dict[str, Any]:
        edges = [
            Edge(source=node_id, predicate=item.predicate, target=item.target)
            for item in body.edges
        ]
        return _write(lambda: manage.replace_out_edges(api.store, node_id, edges))

    @app.put("/api/v1/kb/nodes/{node_id:path}")
    def update_node(node_id: str, body: NodeUpdate) -> dict[str, Any]:
        return _write(
            lambda: manage.update_node(
                api.store, node_id, expected_revision=body.expected_revision, patch=body.to_patch()
            )
        )

    @app.post("/api/v1/kb/nodes/{node_id:path}/deprecate")
    def deprecate_node(node_id: str, body: DeprecateRequest) -> dict[str, Any]:
        return _write(
            lambda: manage.deprecate_node(
                api.store,
                node_id,
                superseded_by=body.superseded_by,
                reason=body.reason,
                actor=body.actor,
            )
        )

    @app.delete("/api/v1/kb/nodes/{node_id:path}")
    def delete_node(
        node_id: str,
        revision: str = Query(min_length=1),
        reason: str = "",
        actor: str = "ui",
    ) -> dict[str, Any]:
        return _write(
            lambda: manage.delete_node(
                api.store, node_id, expected_revision=revision, reason=reason, actor=actor
            )
        )

    # ---- 回收站 ----

    @app.get("/api/v1/kb/trash")
    def list_trash(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return manage.list_trash(api.store, limit=limit)

    @app.post("/api/v1/kb/trash/restore")
    def restore_trash(body: RestoreRequest) -> dict[str, Any]:
        return _write(lambda: manage.restore_node(api.store, body.trash))

    # ---- 检索与审计 ----

    @app.get("/api/v1/kb/search")
    def search(
        q: str,
        project: str | None = None,
        kinds: str | None = None,
        tier: str = "all",
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        kind_list = [item for item in (kinds or "").split(",") if item] or None
        return query.search(api.store, q, project=project, kinds=kind_list, tier=tier, limit=limit)

    @app.get("/api/v1/kb/audit")
    def audit(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return query.audit_list(api.store, limit=limit, offset=offset)

    # ---- 投影 ----

    @app.get("/api/v1/kb/rebuild")
    @app.get("/api/v1/kb/projection")
    def rebuild_status() -> dict[str, Any]:
        return api.rebuild_status()

    @app.post("/api/v1/kb/rebuild", response_model=None)
    def rebuild() -> Any:
        try:
            return api.rebuild_now()
        except Exception as exc:  # noqa: BLE001 - 返回 500 + 原因，让 UI 展示
            return JSONResponse(
                status_code=500,
                content={
                    "code": 2001,
                    "message": f"投影重建失败: {type(exc).__name__}: {exc}",
                    "data": api.rebuild_status(),
                },
            )

    # ---- 静态前端（打包产物）----

    index = web_dist / "index.html" if web_dist is not None else None
    if web_dist is not None and index is not None and index.is_file():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", response_model=None)
        def spa(path: str) -> FileResponse | JSONResponse:
            if path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"code": 1011, "message": "未知接口", "data": {"path": path}},
                )
            candidate = web_dist / path
            if path and candidate.is_file() and web_dist in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(index)

    if graph_restarter is not None and graph_out.is_file():
        graph_restarter.start()

    return app


class _GraphRestarter:
    """可选：由 kb-api 拉起 explorer 子进程，投影重建后自动重启它。

    explorer 只在启动时读一次 kg.json，不重启就看不到新图谱；本地形态下
    让 kb-api 托管它是最省心的做法。未设置 `MEMHUB_KB_GRAPH_PORT` 时本类不生效。
    """

    def __init__(self, graph: Path, port: int) -> None:
        self.graph = graph
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls) -> _GraphRestarter | None:
        port = os.environ.get("MEMHUB_KB_GRAPH_PORT", "").strip()
        if not port:
            return None
        graph = Path(os.environ.get("MEMHUB_KB_GRAPH", DEFAULT_GRAPH))
        return cls(graph, int(port))

    def start(self) -> None:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return
            env = os.environ.copy()
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
            self.process = subprocess.Popen(
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def restart(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self.start()

    def stop(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
        if process is not None and process.poll() is None:
            process.terminate()
