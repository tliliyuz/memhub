"""子进程调用的唯一异步入口。

为什么不用 `asyncio.create_subprocess_exec` / `anyio.run_process`：Windows 上
psycopg 的异步驱动要求 `SelectorEventLoop`，而 SelectorEventLoop 不支持 asyncio
子进程（直接 `NotImplementedError`）。本模块把 `subprocess` 的阻塞调用放进 anyio
工作线程，调用方看到的仍是可 `await` 的协程，事件循环不会被卡住。

全仓的 `subprocess` 调用只允许出现在本文件（`scripts/check_async_io.py` 白名单）。
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio

Command = Sequence[str | Path]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _prepare(
    args: Command, env: Mapping[str, str] | None, cwd: str | Path | None
) -> tuple[list[str], dict[str, str] | None, str | None]:
    command = [str(item) for item in args]
    child_env = None if env is None else {str(key): str(value) for key, value in env.items()}
    return command, child_env, None if cwd is None else str(cwd)


async def run_command(
    args: Command,
    *,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    capture: bool = True,
) -> CommandResult:
    """跑命令到结束；超时抛 `TimeoutError`，命令非零退出不抛异常。"""
    command, child_env, workdir = _prepare(args, env, cwd)

    def _run() -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=capture,
                timeout=timeout,
                env=child_env,
                cwd=workdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{command[0]} 超时（{timeout}s）") from exc
        return CommandResult(
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        )

    return await anyio.to_thread.run_sync(_run)


async def spawn(
    args: Command,
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Any:
    """启动长驻子进程并立即返回；stdout/stderr 丢弃，退出码用 `exit_code` 查。"""
    command, child_env, workdir = _prepare(args, env, cwd)

    def _spawn() -> Any:
        return subprocess.Popen(
            command,
            env=child_env,
            cwd=workdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return await anyio.to_thread.run_sync(_spawn)


def exit_code(process: Any) -> int | None:
    """`None` 表示仍在运行；`poll()` 只做一次非阻塞 waitpid，不占线程。"""
    return None if process is None else process.poll()


def terminate(process: Any) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()


def kill(process: Any) -> None:
    if process is None:
        return
    try:
        process.kill()
    except OSError:
        pass


__all__ = ["CommandResult", "exit_code", "kill", "run_command", "spawn", "terminate"]
