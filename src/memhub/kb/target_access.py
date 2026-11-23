"""采集入口与 worker 共用的目标授权；注册设备本身不授予写权限。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memhub.contract import explicit_project
from memhub.kb import archive, catalog
from memhub.kb.manage import ConflictError
from memhub.kb.store import KnowledgeStore


class TargetUnavailable(Exception):
    """无法确认当前策略或登记状态。不得沿用旧权限。"""


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


async def registered_active(store: KnowledgeStore, project: str) -> bool:
    """检查严格登记与活动目录，不使用用于展示的目录发现规则。"""
    if explicit_project(project) is None:
        return False
    try:
        if await archive.path_kind(store.root) != "dir":
            raise TargetUnavailable("target registry unavailable")
        pending = await archive.checked_path(store.root, archive.PENDING)
        if await archive.path_kind(pending) is not None:
            raise TargetUnavailable("target registry unavailable")
        _, registry = await catalog._strict_registry(store)
        if not any(entry["id"] == project for entry in registry["kbs"]):
            return False
        blocked = await archive.checked_path(store.root, f"{archive.ARCHIVES}/blocked/{project}")
        if await archive.path_kind(blocked) is not None:
            return False
    except (ConflictError, OSError) as exc:
        raise TargetUnavailable("target registry unavailable") from exc
    # 已登记但指向非普通目录（含符号链接和 Windows 重解析点）的目标绝不活动。
    try:
        return await archive.path_kind(store.root / project) == "dir"
    except ConflictError:
        return False
    except OSError as exc:
        raise TargetUnavailable("target registry unavailable") from exc


class TargetPolicy:
    def __init__(self, knowledge_dir: Path, grants_path: Path) -> None:
        self.store = KnowledgeStore(knowledge_dir)
        self.grants_path = grants_path

    async def granted(self, device_id: str) -> frozenset[str]:
        try:
            raw = await archive.read_optional(self.grants_path)
            if raw is None:
                raise TargetUnavailable("target grants unavailable")
            obj = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(obj, dict) or set(obj) != {"devices"}:
                raise ValueError("grant envelope")
            devices = obj["devices"]
            if not isinstance(devices, dict):
                raise TypeError("grant devices")
            for device, targets in devices.items():
                if (
                    not device
                    or device == "*"
                    or not isinstance(targets, list)
                    or any(explicit_project(target) is None for target in targets)
                    or len(set(targets)) != len(targets)
                ):
                    raise ValueError("grant entry")
            return frozenset(devices.get(device_id, []))
        except (ConflictError, OSError, TypeError, ValueError) as exc:
            raise TargetUnavailable("target grants unavailable") from exc

    async def active(self, project: str) -> bool:
        return await registered_active(self.store, project)
