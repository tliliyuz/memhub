"""MCP 工具实现，与传输层无关；四个读工具，三个写候选工具。"""

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
    ReadInput,
    RelatedInput,
    SearchInput,
    ToolInput,
    UpdateCandidateInput,
    WriteCandidateInput,
)
from memhub.kb import candidates, manage, query
from memhub.kb.candidates import CandidateConflict, CandidateRejected
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetUnavailable

_DEFINITIONS: dict[str, tuple[type[ToolInput], str]] = {
    "kb_search": (SearchInput, "关键词检索知识库；默认只返回 canonical 节点。"),
    "kb_read": (ReadInput, "按完整 ID 读取一条知识的正文、元数据和可见关系。"),
    "kb_related": (RelatedInput, "查邻接子图，最多两跳。"),
    "kb_audit_list": (AuditInput, "只读分页列出治理问题。"),
    "kb_write_candidate": (
        WriteCandidateInput,
        (
            "写入一条 tier=candidate 候选知识，只创建不更新。必须显式给出 project、"
            "kind、slug、title、body 与至少一条 evidence（SourceRef 形状）。"
            "只写能在其他会话复用、并有原文支撑的结论；寒暄、进度汇报、临时状态、"
            "原始日志和未验证猜测不要写。成功返回 id、tier、revision 与 commit；"
            "slug 冲突、正文重复、证据不合格或超过每日上限时返回 isError 与 data.reason。"
        ),
    ),
    "kb_update_candidate": (
        UpdateCandidateInput,
        (
            "按 id 与 expected_revision 更新自己写的候选，只改 title、body、tags、"
            "confidence，至少给一项；revision 取自 kb_read 的返回值，过期会被拒绝。"
            "只能改 tier=candidate，命中 canonical 或 deprecated 一律拒绝且不改文件。"
            "成功返回新的 revision；正文重复、内容门槛未过时返回 isError 与 data.reason。"
        ),
    ),
    "kb_deprecate": (
        DeprecateInput,
        (
            "按 id 与 expected_revision 把候选标记为废弃并保留文件，不物理删除。"
            "reason 记入 deprecated_reason 并追加到正文；superseded_by 可选，用于指向"
            "替代节点。只能废弃 tier=candidate，canonical 不受影响。成功返回新的 revision。"
        ),
    ),
}
# 写工具集合：读凭据看不到，调用也直接拒绝。
_WRITE_TOOLS = frozenset({"kb_write_candidate", "kb_update_candidate", "kb_deprecate"})
TOOLS = [
    {
        "name": name,
        "description": description,
        "inputSchema": model.model_json_schema(),
        "annotations": {"readOnlyHint": name not in _WRITE_TOOLS},
    }
    for name, (model, description) in _DEFINITIONS.items()
]
TOOL_NAMES = frozenset(_DEFINITIONS)


def tools_for(*, writable: bool) -> list[dict[str, Any]]:
    """按作用域裁剪工具列表；读凭据看不到写工具。"""
    return [tool for tool in TOOLS if writable or tool["name"] not in _WRITE_TOOLS]


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
    grant_id: str = "stdio",
) -> dict[str, Any]:
    """`projects=None` 仅用于本机全库调用；空集合没有任何权限。"""
    definition = _DEFINITIONS.get(name)
    if definition is None:
        return _error(-32602, "未知工具")
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
        outcome = "ok" if payload["commit"] else "ok_without_commit"
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
