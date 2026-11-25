"""采集入口与 worker 共用的目标边界：已登记且活动。

具体判据由存储对象给出（`project_status`）：文件版看 `.kbs.json` 与活动目录，
PG 版看 `kb_projects`。`TargetUnavailable` 仍从本模块导出，兼容既有导入方。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from memhub.contract import explicit_project
from memhub.kb.errors import TargetUnavailable


class ProjectSource(Protocol):
    """只回答登记状态；文件版与 PG 版存储都满足。"""

    async def project_status(self, project: str) -> str: ...


__all__ = [
    "ProjectSource",
    "TargetRegistry",
    "TargetStatus",
    "TargetUnavailable",
    "registered_active",
    "target_status",
]


class TargetStatus(StrEnum):
    ACTIVE = "active"
    UNREGISTERED = "unregistered"
    INACTIVE = "inactive"
    INVALID = "invalid"


async def target_status(store: ProjectSource, project: str) -> TargetStatus:
    """目标当前状态；登记不可读或归档事务未完成时抛 `TargetUnavailable`。"""
    if explicit_project(project) is None:
        return TargetStatus.INVALID
    return TargetStatus(await store.project_status(project))


async def registered_active(store: ProjectSource, project: str) -> bool:
    """检查严格登记与活动目录，不使用用于展示的目录发现规则。"""
    return await target_status(store, project) is TargetStatus.ACTIVE


class TargetRegistry:
    """只回答「这个库现在能不能写」；不提供设备授权文件。"""

    def __init__(self, source: ProjectSource) -> None:
        self.store = source

    async def active(self, project: str) -> bool:
        return await registered_active(self.store, project)
