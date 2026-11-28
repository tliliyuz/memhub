"""MCP 调用轨迹的只读查询（ADR-0015，规格 docs/plans/mcp-trace-spec.md §6）。

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
        "event": row.event,
        "tool": row.tool,
        "status": row.status,
        "http_status": row.http_status,
        "error_code": row.error_code,
        "error_kind": row.error_kind,
        "duration_ms": row.duration_ms,
        "result_bytes": row.result_bytes,
        "tool_count": row.tool_count,
        "projects": list(row.projects) if row.projects is not None else None,
        "client": row.client,
    }


async def mcp_traces(
    store: PgKnowledgeStore,
    *,
    limit: int = 50,
    offset: int = 0,
    event: str = "call",
    tool: str | None = None,
    status: str | None = None,
    credential: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """分页列表，`called_at` 倒序（同刻按 `id` 倒序），过滤条件全部生效。"""
    conditions = []
    if event:
        conditions.append(KbMcpTrace.event == event)
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
    """近 `days` 天的调用汇总：状态分布、按工具、按凭据，以及连接漏斗。

    既有统计（`total`/`ok`/`error`/`rejected`/`tools`/`credentials`）只看
    `event=call`，保持原有语义；漏斗另取发现层事件（ADR-0018）。
    """
    since = datetime.now(UTC) - timedelta(days=days)
    call_events = (KbMcpTrace.called_at >= since, KbMcpTrace.event == "call")
    async with store.sessions() as session:
        counts = (
            await session.execute(
                select(KbMcpTrace.event, KbMcpTrace.status, func.count())
                .where(KbMcpTrace.called_at >= since)
                .group_by(KbMcpTrace.event, KbMcpTrace.status)
            )
        ).all()
        avg_tools = await session.scalar(
            select(func.avg(KbMcpTrace.tool_count)).where(
                KbMcpTrace.called_at >= since,
                KbMcpTrace.event == "list_tools",
                KbMcpTrace.status == "ok",
                KbMcpTrace.tool_count.is_not(None),
            )
        )
        rows = (await session.scalars(select(KbMcpTrace).where(*call_events))).all()

    totals: dict[tuple[str, str], int] = {
        (str(event), str(status)): int(count) for event, status, count in counts
    }

    def count_of(event: str, status: str | None = None) -> int:
        if status is not None:
            return totals.get((event, status), 0)
        return sum(value for (item_event, _), value in totals.items() if item_event == event)

    total = count_of("call")
    ok = count_of("call", "ok")
    error = count_of("call", "error")
    rejected = count_of("call", "rejected")
    # 旧协议握手与现代协议的连接探测各算一次连接尝试（ADR-0022）。
    connections = count_of("initialize", "ok") + count_of("discover", "ok")
    listings = count_of("list_tools", "ok")
    calls = ok + error

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
        "total": total,
        "ok": ok,
        "error": error,
        "rejected": rejected,
        "tools": tool_items,
        "credentials": credential_items,
        "funnel": {
            "connections": connections,
            "listings": listings,
            "calls": calls,
            "listings_per_connection": (round(listings / connections, 2) if connections else 0.0),
            "calls_per_listing": round(calls / listings, 2) if listings else 0.0,
            "avg_tools": round(float(avg_tools), 2) if avg_tools is not None else 0,
        },
    }
