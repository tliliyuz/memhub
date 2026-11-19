"""测试级事件循环配置。

psycopg 的异步实现不支持 Windows 默认的 ProactorEventLoop；本机跑 PG 契约测试时
必须换成 SelectorEventLoop（生产/CI 在 Linux 上不受影响）。
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

import pytest


@pytest.fixture(scope="session")
def _asyncio_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None
