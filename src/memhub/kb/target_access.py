"""采集入口与 worker 共用的目标边界：已登记且活动。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from memhub.contract import explicit_project
from memhub.kb import archive, catalog
from memhub.kb.manage import ConflictError
from memhub.kb.store import KnowledgeStore


class TargetUnavailable(Exception):
    """无法确认当前登记状态。不得沿用旧权限。"""


class TargetStatus(StrEnum):
    ACTIVE = "active"
    UNREGISTERED = "unregistered"
    INACTIVE = "inactive"
    INVALID = "invalid"


async def target_status(store: KnowledgeStore, project: str) -> TargetStatus:
    """目标当前状态：只认严格登记 + 活动普通目录。

    登记文件不可读、归档事务未完成时抛 `TargetUnavailable`，调用方按可重试的
    服务端错误处理；不能用「猜一个默认值」继续写。
    """
    if explicit_project(project) is None:
        return TargetStatus.INVALID
    try:
        if await archive.path_kind(store.root) != "dir":
            raise TargetUnavailable("target registry unavailable")
        pending = await archive.checked_path(store.root, archive.PENDING)
        if await archive.path_kind(pending) is not None:
            raise TargetUnavailable("target registry unavailable")
        _, registry = await catalog._strict_registry(store)
        if not any(entry["id"] == project for entry in registry["kbs"]):
            return TargetStatus.UNREGISTERED
        blocked = await archive.checked_path(store.root, f"{archive.ARCHIVES}/blocked/{project}")
        if await archive.path_kind(blocked) is not None:
            return TargetStatus.INACTIVE
    except (ConflictError, OSError) as exc:
        raise TargetUnavailable("target registry unavailable") from exc
    # 已登记但指向非普通目录（含符号链接和 Windows 重解析点）的目标绝不活动。
    try:
        kind = await archive.path_kind(store.root / project)
    except ConflictError:
        return TargetStatus.INACTIVE
    except OSError as exc:
        raise TargetUnavailable("target registry unavailable") from exc
    return TargetStatus.ACTIVE if kind == "dir" else TargetStatus.INACTIVE


async def registered_active(store: KnowledgeStore, project: str) -> bool:
    """检查严格登记与活动目录，不使用用于展示的目录发现规则。"""
    return await target_status(store, project) is TargetStatus.ACTIVE


class TargetRegistry:
    """只回答「这个库现在能不能写」；不提供设备授权文件。"""

    def __init__(self, knowledge_dir: Path) -> None:
        self.store = KnowledgeStore(knowledge_dir)

    async def active(self, project: str) -> bool:
        return await registered_active(self.store, project)
