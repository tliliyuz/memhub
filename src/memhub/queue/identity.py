"""队列身份常量与目标冲突（与具体存储无关）。

`kb-console` 是管理台上传保留的设备身份：它不能出现在采集入口，也不能被采集器
冒用。批次目标冲突（同一 sha 被指向另一个知识库）在 ingest 与上传两条路径上共用
同一个异常类型。
"""

from __future__ import annotations

import os
import re
from pathlib import PureWindowsPath

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
CONSOLE_DEVICE = "kb-console"


class BatchTargetConflict(Exception):
    """同一内容已落库到另一个目标，或队列身份不一致。"""

    def __init__(self) -> None:
        super().__init__("queue target conflict")


def safe_id(value: str) -> str:
    """沿用旧的地址映射规则；Windows 文件系统会忽略分量末尾的点。"""
    cleaned = _SAFE.sub("_", value)[:100]
    return cleaned.rstrip(".") if os.name == "nt" else cleaned


def component_valid(part: str) -> bool:
    if not part or part in {".", ".."}:
        return False
    if os.name != "nt":
        return True
    isreserved = getattr(os.path, "isreserved", None)
    return not (isreserved(part) if isreserved is not None else PureWindowsPath(part).is_reserved())


def collector_device_reserved(device_id: str) -> bool:
    return safe_id(device_id).rstrip(".").lower() == CONSOLE_DEVICE


__all__ = [
    "CONSOLE_DEVICE",
    "BatchTargetConflict",
    "collector_device_reserved",
    "component_valid",
    "safe_id",
]
