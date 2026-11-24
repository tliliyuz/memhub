"""整库归档的文件快照与可续做的真源操作；活跃数据格式不变。"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from zipfile import BadZipFile, ZipFile

import anyio
from anyio import Path as AsyncPath

from memhub.kb.manage import ConflictError, NotFoundError, write_lock
from memhub.kb.store import KnowledgeStore

ARCHIVES = "_kb_archives"
ARCHIVE_ID = re.compile(r"[0-9a-f]{32}")
MARKER = f"{ARCHIVES}/projection-dirty"
PENDING = f"{ARCHIVES}/pending.json"


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or "/".join(parts) != relative
        or any(
            part in {"..", "."}
            or any(c in part for c in "\\:\0")
            or (
                os.name == "nt"
                and (part.endswith((".", " ")) or PureWindowsPath(part).is_reserved())
            )
            for part in parts
        )
        or relative.startswith("/")
    ):
        raise ConflictError("归档路径不合法")
    return root.joinpath(*parts)


async def path_kind(path: Path) -> str | None:
    try:
        info = await AsyncPath(path).lstat()
    except FileNotFoundError:
        return None
    if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ConflictError("归档路径含重解析点", {"name": path.name})
    mode = info.st_mode
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    raise ConflictError("归档路径不是普通文件或目录", {"name": path.name})


async def checked_path(root: Path, relative: str) -> Path:
    path = _path(root, relative)
    parent = root
    for part in path.relative_to(root).parts[:-1]:
        parent = parent / part
        if await path_kind(parent) == "file":
            raise ConflictError("归档路径的上级不是目录", {"name": parent.name})
    return path


async def read_optional(path: Path) -> bytes | None:
    kind = await path_kind(path)
    if kind is None:
        return None
    if kind != "file":
        raise ConflictError("归档路径不是普通文件", {"name": path.name})
    return await AsyncPath(path).read_bytes()


async def projection_dirty(root: Path) -> bool:
    for name in (PENDING, MARKER):
        if await path_kind(await checked_path(root, name)) is not None:
            return True
    return False


async def clear_projection_dirty(root: Path) -> None:
    path = await checked_path(root, MARKER)
    if await path_kind(path) == "file":
        await AsyncPath(path).unlink()
        await _sync(path.parent)


async def ensure_missing(path: Path) -> None:
    if await path_kind(path) is not None:
        raise ConflictError("恢复目标已存在", {"name": path.name})


def _sync_dir(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _replace(path: Path, value: bytes, staging: Path | None) -> None:
    tmp = (staging or path.parent) / f".{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        _sync_dir(path.parent)
        if staging is not None and staging != path.parent:
            _sync_dir(staging)
    finally:
        tmp.unlink(missing_ok=True)


async def replace(path: Path, value: bytes, *, staging: Path | None = None) -> None:
    await anyio.to_thread.run_sync(_replace, path, value, staging)


async def _sync(path: Path) -> None:
    await anyio.to_thread.run_sync(_sync_dir, path)


async def make_archive_dirs(*paths: Path) -> None:
    for path in paths:
        if await path_kind(path) == "dir":
            continue
        if await path_kind(path.parent) != "dir":
            await make_archive_dirs(path.parent)
        await AsyncPath(path).mkdir()
        await _sync(path.parent)


def _pack(manifest: dict[str, Any], blobs: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as bundle:
        for name, blob in blobs.items():
            bundle.writestr(name, blob)
        bundle.writestr(
            "manifest.json",
            json_bytes(
                {
                    "version": 1,
                    "payload": manifest,
                    "sha256": {
                        name: hashlib.sha256(data).hexdigest() for name, data in blobs.items()
                    },
                }
            ),
        )
    return buffer.getvalue()


def _unpack(value: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        with ZipFile(io.BytesIO(value)) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest["version"] != 1 or not isinstance(manifest["payload"], dict):
                raise ValueError("version")
            hashes = manifest["sha256"]
            if sorted(bundle.namelist()) != sorted(["manifest.json", *hashes]):
                raise ValueError("entries")
            blobs = {name: bundle.read(name) for name in hashes}
            if any(
                hashlib.sha256(data).hexdigest() != hashes[name] for name, data in blobs.items()
            ):
                raise ValueError("checksum")
            return manifest["payload"], blobs
    except (BadZipFile, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise ConflictError("归档包或操作记录损坏") from exc


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def pack_bundle(meta: dict[str, Any], blobs: dict[str, bytes]) -> bytes:
    """把元数据与附件打成可校验的 zip 字节串（PG 版快照直接入 `bytea`）。"""
    return await anyio.to_thread.run_sync(_pack, meta, blobs)


async def unpack_bundle(value: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    """解包并校验附件摘要；损坏时抛 `ConflictError`。"""
    return await anyio.to_thread.run_sync(_unpack, value)


async def save_bundle(path: Path, meta: dict[str, Any], blobs: dict[str, bytes]) -> str:
    value = await anyio.to_thread.run_sync(_pack, meta, blobs)
    await replace(path, value)
    return await anyio.to_thread.run_sync(_digest, value)


async def load_bundle(path: Path, sha256: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    value = await read_optional(path)
    if value is None:
        raise NotFoundError("归档包不存在")
    if await anyio.to_thread.run_sync(_digest, value) != sha256:
        raise ConflictError("归档包校验失败")
    return await anyio.to_thread.run_sync(_unpack, value)


@dataclass(frozen=True)
class Step:
    path: str
    before: bytes | str | None
    after: bytes | str | None


async def _current(path: Path) -> bytes | str | None:
    kind = await path_kind(path)
    return await AsyncPath(path).read_bytes() if kind == "file" else kind


def _unexpected(step: Step) -> ConflictError:
    return ConflictError("真源版本与归档操作记录不符", {"path": step.path})


async def _preflight(root: Path, steps: list[Step], *, replay: bool = False) -> None:
    inventory = {step.path: step for step in steps}
    if len(inventory) != len(steps):
        raise ConflictError("归档操作包含重复路径")
    for step in steps:
        path = await checked_path(root, step.path)
        current = await _current(path)
        if current != step.before and not (replay and current == step.after):
            raise _unexpected(step)
        if current == "dir" and step.after is None:
            async for child in AsyncPath(path).iterdir():
                planned = inventory.get(child.relative_to(root).as_posix())
                if planned is None or planned.after is not None:
                    raise _unexpected(step)


async def _apply(root: Path, step: Step) -> None:
    path = await checked_path(root, step.path)
    current = await _current(path)
    if current == step.after:
        return
    if current != step.before:
        raise _unexpected(step)
    if step.after == "dir":
        await AsyncPath(path).mkdir()
        await _sync(path.parent)
    elif isinstance(step.after, bytes):
        await replace(path, step.after, staging=root / ARCHIVES)
    else:
        if current == "dir":
            await AsyncPath(path).rmdir()
        else:
            await AsyncPath(path).unlink()
        await _sync(path.parent)


def _step_payload(steps: list[Step]) -> tuple[dict[str, Any], dict[str, bytes]]:
    blobs = {}
    records = []
    for index, step in enumerate(steps):
        values: list[dict[str, str] | str | None] = []
        for label, value in (("before", step.before), ("after", step.after)):
            if isinstance(value, bytes):
                name = f"{index}/{label}"
                blobs[name] = value
                values.append({"blob": name})
            else:
                values.append(value)
        records.append([step.path, *values])
    return {"steps": records}, blobs


async def _clear_pending(root: Path) -> None:
    await AsyncPath(root / PENDING).unlink()
    await _sync(root / ARCHIVES)


async def execute(root: Path, archive_id: str, steps: list[Step]) -> None:
    """持有写锁；先持久化完整操作，再应用真源变更。"""
    journal_id = uuid.uuid4().hex
    relative = f"{ARCHIVES}/{archive_id}/{journal_id}.zip"
    pending = await checked_path(root, PENDING)
    await ensure_missing(pending)
    marker = await checked_path(root, MARKER)
    steps = [*steps, Step(MARKER, await read_optional(marker), journal_id.encode())]
    await _preflight(root, steps)
    meta, blobs = _step_payload(steps)
    journal = root / relative
    digest = await save_bundle(journal, meta, blobs)
    await replace(pending, json_bytes({"journal": relative, "sha256": digest}))
    attempted: list[Step] = []
    try:
        for step in steps:
            attempted.append(step)
            await _apply(root, step)
    except BaseException:
        with anyio.CancelScope(shield=True):
            for step in reversed(attempted):
                await _apply(root, Step(step.path, step.after, step.before))
            await _clear_pending(root)
            await AsyncPath(journal).unlink()
        raise
    with anyio.CancelScope(shield=True):
        await _clear_pending(root)
        await AsyncPath(journal).unlink()


async def recover(store: KnowledgeStore) -> bool:
    async with write_lock(store.root, recovery=True):
        marker = await read_optional(await checked_path(store.root, PENDING))
        if marker is None:
            return False
        try:
            intent = json.loads(marker)
            relative = intent["journal"]
            if not re.fullmatch(r"_kb_archives/[0-9a-f]{32}/[0-9a-f]{32}\.zip", relative):
                raise ValueError("journal")
            path = await checked_path(store.root, relative)
            meta, blobs = await load_bundle(path, intent["sha256"])
            steps = []
            for name, old, new in meta["steps"]:
                states = []
                for value in (old, new):
                    if isinstance(value, dict):
                        states.append(blobs[value["blob"]])
                    elif value is None or value == "dir":
                        states.append(value)
                    else:
                        raise ValueError("step state")
                steps.append(Step(name, *states))
            if not steps or steps[-1].path != MARKER:
                raise ValueError("projection marker")
        except (TypeError, KeyError, ValueError, NotFoundError) as exc:
            raise ConflictError("归档操作记录损坏") from exc
        await _preflight(store.root, steps, replay=True)
        for step in steps:
            await _apply(store.root, step)
        await _clear_pending(store.root)
        await AsyncPath(path).unlink()
        return True
