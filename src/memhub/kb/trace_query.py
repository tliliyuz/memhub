"""MCP 调用轨迹的只读查询（ADR-0014，规格 docs/plans/mcp-trace-spec.md §6）。

管理台列表与汇总；真源是 `kb_mcp_trace`，只读不写。只对 `PgKnowledgeStore`
开放，非 PG 存储由调用方返回 503/`2001`。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from memhub.kb.models import KbMcpTrace
from memhub.kb.pgstore import PgKnowledgeStore


def _item(row: KbMcpTrace) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "rpc_id": row.rpc_id,
        "called_at": row.called_at,
        "credential": {"id": row.credential_id, "name": row.credential_name},
        "tool": row.tool,
        "status": row.status,
        "http_status": row.http_status,
        "error_code": row.error_code,
        "error_kind": row.error_kind,
        "duration_ms": row.duration_ms,
        "result_bytes": row.result_bytes,
        "projects": list(row.projects) if row.projects is not None else None,
        "client": row.client,
    }


async def mcp_traces(
    store: PgKnowledgeStore,
    *,
    limit: int = 50,
    offset: int = 0,
    tool: str | None = None,
    status: str | None = None,
    credential: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """分页列表，`called_at` 倒序（同刻按 `id` 倒序），过滤条件全部生效。"""
    conditions = []
    if tool:
        conditions.append(KbMcpTrace.tool == tool)
    if status:
        conditions.append(KbMcpTrace.status == status)
    if credential:
        conditions.append(
            (KbMcpTrace.credential_id == credential) | (KbMcpTrace.credential_name == credential)
        )
    if since is not None:
        conditions.append(KbMcpTrace.called_at >= since)
    if until is not None:
        conditions.append(KbMcpTrace.called_at <= until)
    async with store.sessions() as session:
        total = await session.scalar(
            select(func.count()).select_from(KbMcpTrace).where(*conditions)
        )
        rows = (
            await session.scalars(
                select(KbMcpTrace)
                .where(*conditions)
                .order_by(KbMcpTrace.called_at.desc(), KbMcpTrace.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    return {
        "items": [_item(row) for row in rows],
        "total": int(total or 0),
        "offset": offset,
        "limit": limit,
    }


async def mcp_traces_summary(store: PgKnowledgeStore, *, days: int = 7) -> dict[str, Any]:
    """近 `days` 天的调用汇总：状态分布、按工具、按凭据。"""
    since = datetime.now(UTC) - timedelta(days=days)
    async with store.sessions() as session:
        scoped = select(KbMcpTrace).where(KbMcpTrace.called_at >= since)
        total = await session.scalar(select(func.count()).select_from(scoped.subquery()))
        ok = await session.scalar(
            select(func.count()).select_from(scoped.where(KbMcpTrace.status == "ok").subquery())
        )
        error = await session.scalar(
            select(func.count()).select_from(scoped.where(KbMcpTrace.status == "error").subquery())
        )
        rejected = await session.scalar(
            select(func.count()).select_from(
                scoped.where(KbMcpTrace.status == "rejected").subquery()
            )
        )
        rows = (
            await session.scalars(select(KbMcpTrace).where(KbMcpTrace.called_at >= since))
        ).all()

    tools: dict[str, dict[str, Any]] = {}
    credentials: dict[str, dict[str, Any]] = {}
    for row in rows:
        stat = tools.setdefault(
            row.tool or "(unknown)",
            {"tool": row.tool or "(unknown)", "count": 0, "ok": 0, "error": 0, "rejected": 0},
        )
        stat["count"] += 1
        stat[row.status] = stat.get(row.status, 0) + 1
        if row.status != "rejected":
            stat.setdefault("_ms", []).append(row.duration_ms)
        credential_id = row.credential_id or ""
        entry = credentials.setdefault(
            credential_id,
            {"id": credential_id, "name": row.credential_name, "count": 0},
        )
        entry["count"] += 1
        if entry["name"] is None and row.credential_name is not None:
            entry["name"] = row.credential_name
    tool_items = []
    for stat in tools.values():
        durations = stat.pop("_ms", [])
        stat["avg_ms"] = round(sum(durations) / len(durations)) if durations else 0
        tool_items.append(stat)
    tool_items.sort(key=lambda item: (-item["count"], item["tool"]))
    credential_items = sorted(credentials.values(), key=lambda item: (-item["count"], item["id"]))
    return {
        "since": since.isoformat(),
        "days": days,
        "total": int(total or 0),
        "ok": int(ok or 0),
        "error": int(error or 0),
        "rejected": int(rejected or 0),
        "tools": tool_items,
        "credentials": credential_items,
    }
