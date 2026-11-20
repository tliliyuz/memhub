"""四个只读工具的共享实现，与传输层无关。"""

from __future__ import annotations

import json
from typing import Any

import anyio
from pydantic import ValidationError
from yaml import YAMLError  # type: ignore[import-untyped]

from memhub.contract.mcp import AuditInput, ReadInput, RelatedInput, SearchInput, ToolInput
from memhub.kb import manage, query
from memhub.kb.reader import ActiveReader
from memhub.kb.store import KnowledgeStore

_DEFINITIONS: dict[str, tuple[type[ToolInput], str]] = {
    "kb_search": (SearchInput, "关键词检索知识库；默认只返回 canonical 节点。"),
    "kb_read": (ReadInput, "按完整 ID 读取一条知识的正文、元数据和可见关系。"),
    "kb_related": (RelatedInput, "查邻接子图，最多两跳。"),
    "kb_audit_list": (AuditInput, "只读分页列出治理问题。"),
}
TOOLS = [
    {
        "name": name,
        "description": description,
        "inputSchema": model.model_json_schema(),
        "annotations": {"readOnlyHint": True},
    }
    for name, (model, description) in _DEFINITIONS.items()
]
TOOL_NAMES = frozenset(_DEFINITIONS)


def _content(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def _error(code: int, message: str) -> dict[str, Any]:
    return _content({"code": code, "message": message}, is_error=True)


async def call_tool(
    name: str,
    arguments: dict[str, Any],
    store: KnowledgeStore,
    *,
    projects: frozenset[str] | None = None,
) -> dict[str, Any]:
    """`None` 仅用于本机全库调用；空集合没有任何权限。"""
    definition = _DEFINITIONS.get(name)
    if definition is None:
        return _error(-32602, "未知工具")
    try:
        # 严格校验协议 JSON，允许 JSON 字符串表示枚举，不允许隐式数字转换。
        args = definition[0].model_validate_json(json.dumps(arguments))
    except (ValidationError, TypeError, ValueError):
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

    try:
        # 归档分多文件更新，仅检查 pending 标记会漏过检查之后启动的写入。
        with anyio.fail_after(5):
            async with manage.write_lock(store.root, timeout=0):
                payload = await _run(
                    args, ActiveReader(store, projects), scoped=projects is not None
                )
        return _content(payload)
    except (manage.WriteDeferred, TimeoutError):
        return _error(3006, "知识库正忙或等待归档恢复，请稍后重试")
    except (query.NotFound, FileNotFoundError):
        return _error(3001, "节点不存在")
    except (OSError, ValueError, TypeError, KeyError, YAMLError):
        return _error(3007, "知识库读取失败")


async def _run(args: ToolInput, reader: ActiveReader, *, scoped: bool) -> dict[str, Any]:
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
        if scoped:
            result["source"] = []
            for key in ("source", "supersedes", "superseded_by"):
                result["frontmatter"].pop(key, None)
            result["frontmatter"]["project"] = args.id.split("/", 1)[0]
        return result
    if isinstance(args, AuditInput):
        return await query.audit_list(reader, limit=args.limit, offset=args.offset)
    raise AssertionError("未注册的工具参数模型")
