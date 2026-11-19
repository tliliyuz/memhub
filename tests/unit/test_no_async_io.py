"""门禁脚本自测：命中同步 I/O / 放行异步实现。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_async_io.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_async_io", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subprocess_run_is_flagged(checker: ModuleType) -> None:
    source = "import subprocess\n\n\ndef f():\n    return subprocess.run(['git', 'status'])\n"
    messages = [message for _, message in checker.find_violations(source, "x.py")]
    assert messages and "subprocess.run" in messages[0]


def test_sync_path_method_is_flagged(checker: ModuleType) -> None:
    source = "from pathlib import Path\n\n\ndef f(p):\n    return Path(p).read_text()\n"
    assert checker.find_violations(source, "x.py")


def test_builtin_open_is_flagged(checker: ModuleType) -> None:
    source = "def f(p):\n    with open(p) as handle:\n        return handle.read()\n"
    assert checker.find_violations(source, "x.py")


def test_time_sleep_and_sync_http_client_are_flagged(checker: ModuleType) -> None:
    source = (
        "import time\nimport httpx\n\n\ndef f():\n    time.sleep(1)\n    return httpx.Client()\n"
    )
    assert len(checker.find_violations(source, "x.py")) == 2


def test_anyio_run_process_is_flagged(checker: ModuleType) -> None:
    source = "import anyio\n\n\nasync def f():\n    await anyio.run_process(['git'])\n"
    assert checker.find_violations(source, "x.py")


def test_async_path_usage_passes(checker: ModuleType) -> None:
    source = (
        "from anyio import Path as AsyncPath\n\n\n"
        "async def f(p):\n"
        "    return await AsyncPath(p).read_text(encoding='utf-8')\n"
    )
    assert checker.find_violations(source, "x.py") == []


def test_allowlisted_proc_module_passes(checker: ModuleType) -> None:
    source = "import subprocess\n\n\ndef f():\n    return subprocess.run(['git'], check=False)\n"
    assert checker.find_violations(source, "src/memhub/kb/proc.py") == []
