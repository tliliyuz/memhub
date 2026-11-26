"""MCP 工具实现，与传输层无关；四个读工具，两个长期记忆读工具，三个写候选工具。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import anyio
from pydantic import ValidationError
from yaml import YAMLError  # type: ignore[import-untyped]

from memhub.contract.mcp import (
    AuditInput,
    DeprecateInput,
    MemoryReadInput,
    MemorySearchInput,
    ReadInput,
    RelatedInput,
    SearchInput,
    ToolInput,
    UpdateCandidateInput,
    WriteCandidateInput,
)
from memhub.kb import candidates, manage, query
from memhub.kb.bm25 import normalize
from memhub.kb.candidates import CandidateConflict, CandidateRejected
from memhub.kb.memory import rank_memories
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetUnavailable

_NO_SNAPSHOT_HINT = "长期记忆尚未发布快照；请管理员在管理台发布后再试。"
_NO_HIT_HINT = "没有匹配的已发布长期记忆；可换关键词或确认快照是否包含相关条目。"

_DEFINITIONS: dict[str, tuple[type[ToolInput], str, str]] = {
    "kb_search": (
        SearchInput,
        "知识库检索 / Search knowledge",
        (
            "跨会话知识库检索：当用户问起以前/上次讨论过的结论、项目决策、笔记或踩坑，"
            "提到记忆/知识库，或需要跨会话复用的项目事实时，先调用本工具。"
            "中英文关键词均可（memory, knowledge base, notes, past sessions）。"
            "默认只返回 canonical 节点；无结果返回空列表与 hint。"
        ),
    ),
    "kb_read": (
        ReadInput,
        "读取知识 / Read knowledge",
        (
            "按完整 ID（project/kind/slug）读取一条知识的正文、元数据与可见关系；"
            "检索命中后用它读全文，正文超长时标记 truncated。"
        ),
    ),
    "kb_related": (
        RelatedInput,
        "关联知识 / Related knowledge",
        "查一条知识的邻接子图（最多两跳），用于补充上下文或追踪相关决策；边最多 100 条并标记截断。",
    ),
    "kb_audit_list": (
        AuditInput,
        "治理审计 / Governance audit",
        "只读分页列出治理问题（矛盾、断链、孤立、低置信、陈旧）；用于健康检查，不是知识检索入口。",
    ),
    "kb_memory_search": (
        MemorySearchInput,
        "长期记忆检索 / Search memory",
        (
            "检索已发布的跨项目长期记忆，返回结论、边界与置信度。长期记忆是判断与归一化准则，"
            "不是事实证据，引用前须回到原始节点核对。凭据需显式开启记忆权限，否则按不存在处理。"
            "无结果返回空列表与 hint。"
        ),
    ),
    "kb_memory_read": (
        MemoryReadInput,
        "读取长期记忆 / Read memory",
        (
            "按 slug 读取一条跨项目长期记忆的结论、失效条件与来源元数据。长期记忆不是事实证据，"
            "不能直接充当引用依据；只返回已发布快照中的 active 条目。凭据需显式开启记忆权限，"
            "否则按不存在处理。"
        ),
    ),
    "kb_write_candidate": (
        WriteCandidateInput,
        "写入知识 / Write knowledge",
        (
            "写入一条 canonical 知识，写入即生效，只创建不更新。必须显式给出 project、"
            "kind、slug、title、body 与至少一条 evidence（SourceRef 形状）。"
            "只写能在其他会话复用、并有原文支撑的结论；寒暄、进度汇报、临时状态、"
            "原始日志和未验证猜测不要写。成功返回 id、tier、revision 与 commit；"
            "slug 冲突、正文重复、证据不合格或超过每日上限时返回 isError 与 data.reason。"
        ),
    ),
    "kb_update_candidate": (
        UpdateCandidateInput,
        "更新知识 / Update knowledge",
        (
            "按 id 与 expected_revision 更新自己创建的节点，只改 title、body、tags、"
            "confidence，至少给一项；revision 取自 kb_read 的返回值，过期会被拒绝。"
            "只能改创建者为本凭据的节点，别人的或已废弃的节点一律拒绝且不改文件。"
            "成功返回新的 revision；正文重复、内容门槛未过时返回 isError 与 data.reason。"
        ),
    ),
    "kb_deprecate": (
        DeprecateInput,
        "废弃知识 / Deprecate knowledge",
        (
            "按 id 与 expected_revision 把自己创建的节点标记为废弃并保留文件，不物理删除。"
            "reason 记入 deprecated_reason 并追加到正文；superseded_by 可选，用于指向"
            "替代节点。只能废弃创建者为本凭据的节点，别人的或已废弃的节点一律拒绝。"
        ),
    ),
}
# 写工具集合：读凭据看不到，调用也直接拒绝。
_WRITE_TOOLS = frozenset({"kb_write_candidate", "kb_update_candidate", "kb_deprecate"})
# 长期记忆工具：凭据未显式开启 `memory` 时不可见，调用按「不存在」拒绝（ADR-0019）。
_MEMORY_TOOLS = frozenset({"kb_memory_search", "kb_memory_read"})
TOOLS = [
    {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": model.model_json_schema(),
        "annotations": {"readOnlyHint": name not in _WRITE_TOOLS},
    }
    for name, (model, title, description) in _DEFINITIONS.items()
]
TOOL_NAMES = frozenset(_DEFINITIONS)


def tools_for(*, writable: bool, memory: bool = False) -> list[dict[str, Any]]:
    """按作用域裁剪工具列表；读凭据看不到写工具，未开启记忆权限时看不到记忆工具。"""
    return [
        tool
        for tool in TOOLS
        if (writable or tool["name"] not in _WRITE_TOOLS)
        and (memory or tool["name"] not in _MEMORY_TOOLS)
    ]


def _content(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def _error(code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data:
        payload["data"] = data
    return _content(payload, is_error=True)


async def call_tool(
    name: str,
    arguments: dict[str, Any],
    store: KnowledgeStore | PgKnowledgeStore,
    *,
    projects: frozenset[str] | None = None,
    writable: bool = False,
    memory: bool = False,
    grant_id: str = "stdio",
) -> dict[str, Any]:
    """`projects=None` 仅用于本机全库调用；空集合没有任何权限。"""
    definition = _DEFINITIONS.get(name)
    if definition is None:
        return _error(-32602, "未知工具")
    if name in _MEMORY_TOOLS and not memory:
        # 与「条目不存在」同码，不向未开启的调用方泄露快照或条目的存在性。
        return _error(3001, "记忆不存在")
    is_write = name in _WRITE_TOOLS
    if is_write and not writable:
        return _error(3004, "该凭据没有写候选的权限")
    try:
        # 严格校验协议 JSON，允许 JSON 字符串表示枚举，不允许隐式数字转换。
        args = definition[0].model_validate_json(json.dumps(arguments))
    except ValidationError as exc:
        if definition[0] is WriteCandidateInput and all(
            issue["loc"][:1] == ("evidence",) for issue in exc.errors(include_input=False)
        ):
            if "evidence" not in arguments:
                return _error(1003, "至少提供一条可追溯的证据", {"reason": "evidence_missing"})
            return _error(1003, "证据不符合 SourceRef 契约", {"reason": "evidence_invalid"})
        return _error(3004, "工具参数不符合输入契约")
    except (TypeError, ValueError):
        return _error(3004, "工具参数不符合输入契约")

    if isinstance(args, (MemorySearchInput, MemoryReadInput)):
        # 长期记忆是跨项目快照，不按 `projects` 过滤；可见性只由 `memory` 开关决定。
        return await _memory_tool(args, store)

    if projects is not None:
        if (
            isinstance(args, SearchInput)
            and args.project is not None
            and args.project not in projects
        ):
            return _error(3003, "该知识库不在授权范围")
        if isinstance(args, ReadInput) and args.id.split("/", 1)[0] not in projects:
            return _error(3001, "节点不存在")

    if isinstance(args, WriteCandidateInput):
        return await _write_tool(
            "kb_write_candidate",
            args,
            store,
            grant_id=grant_id,
            projects=projects,
            action=candidates.create_candidate,
        )
    if isinstance(args, UpdateCandidateInput):
        return await _write_tool(
            "kb_update_candidate",
            args,
            store,
            grant_id=grant_id,
            projects=projects,
            action=candidates.update_candidate,
        )
    if isinstance(args, DeprecateInput):
        return await _write_tool(
            "kb_deprecate",
            args,
            store,
            grant_id=grant_id,
            projects=projects,
            action=candidates.deprecate_candidate,
        )

    try:
        reader = store.scoped_reader(projects)
        if isinstance(store, PgKnowledgeStore):
            # PG 读侧每次查询自成事务，不存在「多文件更新」的中间态。
            payload = await _run(args, store, reader, scoped=projects is not None)
        else:
            # 归档分多文件更新，仅检查 pending 标记会漏过检查之后启动的写入。
            with anyio.fail_after(5):
                async with manage.write_lock(store.root, timeout=0):
                    payload = await _run(args, store, reader, scoped=projects is not None)
        return _content(payload)
    except (manage.WriteDeferred, TimeoutError):
        return _error(3006, "知识库正忙或等待归档恢复，请稍后重试")
    except (query.NotFound, FileNotFoundError):
        return _error(3001, "节点不存在")
    except (OSError, ValueError, TypeError, KeyError, YAMLError):
        return _error(3007, "知识库读取失败")


async def _memory_tool(
    args: MemorySearchInput | MemoryReadInput,
    store: KnowledgeStore | PgKnowledgeStore,
) -> dict[str, Any]:
    """只读当前 `published` 快照；文件存储没有记忆真源，按无快照处理。

    快照是发布时的冻结视图，但废弃要立即生效：这里再用当前条目状态过滤一次，
    只把现在仍为 active 的条目暴露出去。
    """
    if not isinstance(store, PgKnowledgeStore):
        # 文件存储没有记忆真源，按无快照处理。
        if isinstance(args, MemorySearchInput):
            return _content({"results": [], "hint": _NO_SNAPSHOT_HINT})
        return _error(3001, "记忆不存在")
    snapshot = await store.published_memory_snapshot()
    if snapshot is None:
        if isinstance(args, MemorySearchInput):
            return _content({"results": [], "hint": _NO_SNAPSHOT_HINT})
        return _error(3001, "记忆不存在")
    entries = [entry for entry in snapshot["entries"] if isinstance(entry, dict)]
    slugs = [str(entry["slug"]) for entry in entries if isinstance(entry.get("slug"), str)]
    states = await store.memory_states(slugs)
    active = [
        entry
        for entry in entries
        if states.get(str(entry.get("slug")), {}).get("status") == "active"
    ]
    if isinstance(args, MemorySearchInput):
        ranked = rank_memories(active, args.query)[: args.limit]
        ceiling = ranked[0][0] if ranked else 0.0
        payload: dict[str, Any] = {
            "version": snapshot["version"],
            "results": [
                {
                    "slug": entry["slug"],
                    "title": entry["title"],
                    "conclusion": entry["conclusion"],
                    "boundary": entry["boundary"],
                    "confidence": entry["confidence"],
                    "score": normalize(score, ceiling=ceiling),
                }
                for score, entry in ranked
            ],
        }
        if not payload["results"]:
            payload["hint"] = _NO_HIT_HINT
        return _content(payload)
    for entry in active:
        if entry.get("slug") == args.slug:
            return _content(
                {
                    "version": snapshot["version"],
                    "title": entry["title"],
                    "conclusion": entry["conclusion"],
                    "boundary": entry["boundary"],
                    "invalidation": entry["invalidation"],
                    "confidence": entry["confidence"],
                    "status": entry["status"],
                    "revision": entry["revision"],
                    # 证据只保留跨项目可复用的来源元数据，裁剪 node_id。
                    "evidence": [
                        {
                            "project": reference.get("project"),
                            "session": reference.get("session"),
                            "session_ref": reference.get("session_ref"),
                            "observed_at": reference.get("observed_at"),
                        }
                        for reference in entry.get("evidence") or []
                        if isinstance(reference, dict)
                    ],
                }
            )
    return _error(3001, "记忆不存在")


async def _write_tool(
    name: str,
    args: WriteCandidateInput | UpdateCandidateInput | DeprecateInput,
    store: KnowledgeStore | PgKnowledgeStore,
    *,
    grant_id: str,
    projects: frozenset[str] | None,
    action: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """三个写工具共用错误映射与审计；具体校验在 `memhub.kb.candidates`。"""
    outcome = "failed"
    try:
        payload = await action(store, args, grant_id=grant_id, projects=projects)
        outcome = "ok"
        return _content(payload)
    except (CandidateRejected, CandidateConflict) as exc:
        outcome = exc.reason
        return _error(exc.code, exc.message, exc.data)
    except manage.NotFoundError as exc:
        outcome = "not_found"
        return _error(3001, exc.message)
    except (manage.WriteDeferred, TimeoutError):
        outcome = "deferred"
        return _error(3006, "知识库正忙或等待归档恢复，请稍后重试")
    except TargetUnavailable:
        outcome = "deferred"
        return _error(3006, "知识库登记状态暂不可确认，请稍后重试")
    except FileNotFoundError:
        outcome = "project_unavailable"
        return _error(1003, "知识库不可用", {"reason": outcome})
    except (manage.ManageError, OSError, ValueError, TypeError, KeyError, YAMLError):
        return _error(3007, "知识库写入失败")
    finally:
        actor = f"mcp:{grant_id}"
        if isinstance(args, WriteCandidateInput):
            action_name = "create"
            project = args.project
            node_id = f"{args.project}/{args.kind.value}/{args.slug}"
        elif isinstance(args, UpdateCandidateInput):
            action_name, project, node_id = "update", args.id.split("/", 1)[0], args.id
        else:
            action_name = "deprecate"
            project, node_id = args.id.split("/", 1)[0], args.id
        if isinstance(store, PgKnowledgeStore):
            # 写入审计进 `kb_write_audit`（规格 §3.6）；文件存储（测试夹具）只留日志。
            try:
                await store.record_write_audit(
                    actor=actor,
                    project=project,
                    node_id=node_id,
                    action=action_name,
                    result=outcome,
                )
            except Exception:
                logging.getLogger("memhub.mcp.audit").exception("写入审计落库失败 node=%s", node_id)
        logging.getLogger("memhub.mcp.audit").info(
            "tool=%s grant=%s project=%s node=%s result=%s at=%s",
            name,
            grant_id,
            args.id.split("/", 1)[0] if hasattr(args, "id") else args.project,
            args.id if hasattr(args, "id") else f"{args.project}/{args.kind.value}/{args.slug}",
            outcome,
            datetime.now(UTC).isoformat(),
        )


async def _run(
    args: ToolInput,
    store: KnowledgeStore | PgKnowledgeStore,
    reader: query.KnowledgeReader,
    *,
    scoped: bool,
) -> dict[str, Any]:
    if isinstance(args, SearchInput):
        return await query.search(
            reader,
            args.query,
            project=args.project,
            kinds=[kind.value for kind in args.kinds] if args.kinds is not None else None,
            tier=args.tier,
            limit=args.limit,
        )
    if isinstance(args, RelatedInput):
        result = await query.related(
            reader,
            args.id,
            depth=args.depth,
            predicates=[item.value for item in args.predicates]
            if args.predicates is not None
            else None,
            limit=args.limit,
        )
        if len(result["edges"]) > 100:
            result["edges"] = result["edges"][:100]
            result["edges_truncated"] = True
        return result
    if isinstance(args, ReadInput):
        result = await query.read_node(reader, args.id)
        # 写工具的乐观并发前置条件：读完即可带回 expected_revision。
        result["revision"] = await manage.node_revision(store, args.id)
        if scoped:
            result["source"] = []
            for key in ("source", "supersedes", "superseded_by"):
                result["frontmatter"].pop(key, None)
            result["frontmatter"]["project"] = args.id.split("/", 1)[0]
        return result
    if isinstance(args, AuditInput):
        return await query.audit_list(reader, limit=args.limit, offset=args.offset)
    raise AssertionError("未注册的工具参数模型")
