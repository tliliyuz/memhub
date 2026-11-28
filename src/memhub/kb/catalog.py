"""知识库（project）目录与子图（全异步 IO）。

真源按 `<root>/<project>/...` 隔离，这里的 project 就是「知识库」：`sdp-tag`、
`memory-hub` 各自一批节点，互不混杂。本模块只做两件事：

- 维护知识库元数据（`<root>/.kbs.json`：显示名、描述）；目录存在但没登记的
  知识库按目录名兜底展示，保证手工放进来的库也能看到。
- 按知识库导出子图（节点 + 解析后的边 + 度数），给管理台画图用；图谱直接
  读真源，不生成文件投影。

读写都走 `manage.write_lock`，与节点写操作互斥。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anyio import Path as AsyncPath

from memhub.contract import KB_ID_RE
from memhub.kb import archive, manage, query
from memhub.kb.manage import ConflictError, InvalidError, NotFoundError, write_lock
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore

REGISTRY_NAME = ".kbs.json"


def _registry_path(store: KnowledgeStore) -> Path:
    return store.root / REGISTRY_NAME


async def _load(store: KnowledgeStore) -> dict[str, dict[str, Any]]:
    path = _registry_path(store)
    if not await AsyncPath(path).is_file():
        return {}
    try:
        raw = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = raw.get("kbs") if isinstance(raw, dict) else None
    kbs: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("id"):
            kbs[str(item["id"])] = item
    return kbs


async def _save(store: KnowledgeStore, kbs: dict[str, dict[str, Any]]) -> None:
    path = _registry_path(store)
    payload = {"kbs": [kbs[key] for key in sorted(kbs)]}
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        async with await AsyncPath(tmp).open("w", encoding="utf-8", newline="\n") as handle:
            await handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        await AsyncPath(tmp).replace(path)
    except BaseException:
        try:
            await AsyncPath(tmp).unlink()
        except OSError:
            pass
        raise


async def _dirs(store: KnowledgeStore) -> list[str]:
    """真源根下的一级目录即知识库；`_trash` 之类下划线目录不算。"""
    root = AsyncPath(store.root)
    if not await root.is_dir():
        return []
    names: list[str] = []
    async for path in root.iterdir():
        if path.name.startswith(("_", ".")):
            continue
        if await path.is_dir():
            names.append(path.name)
    return sorted(names)


async def exists(store: KnowledgeStore | PgKnowledgeStore, kb_id: str) -> bool:
    """轻量存在性判断：文件版看真源根下一级目录，PG 版看 `kb_projects` 登记。

    不给上传路径用 `list_kbs`：它会逐库扫全部节点，只为判断一个 id 不值当。
    """
    if kb_id.startswith(("_", ".")):
        return False
    if isinstance(store, PgKnowledgeStore):
        return await store.project_exists(kb_id)
    return await AsyncPath(store.root / kb_id).is_dir()


async def _edges(store: KnowledgeStore, project: str) -> list[dict[str, Any]]:
    path = store.edges_path(project)
    if not await AsyncPath(path).is_file():
        return []
    edges: list[dict[str, Any]] = []
    text = await AsyncPath(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if {"source", "predicate", "target"} <= record.keys():
            edges.append(record)
    return edges


async def list_kbs(store: KnowledgeStore | PgKnowledgeStore) -> dict[str, Any]:
    if isinstance(store, PgKnowledgeStore):
        return await store.list_projects()
    registry = await _load(store)
    items: list[dict[str, Any]] = []
    for kb_id in await _dirs(store):
        records = await query.records(store, kb_id)
        meta = registry.get(kb_id, {})
        updated = max(
            (record.node.updated_at for record in records),
            default=None,
        )
        items.append(
            {
                "id": kb_id,
                "name": str(meta.get("name") or kb_id),
                "description": str(meta.get("description") or ""),
                "nodes": len(records),
                "edges": len(await _edges(store, kb_id)),
                "updated_at": updated.isoformat() if updated else None,
                "created_at": meta.get("created_at"),
            }
        )
    return {"items": items, "total": len(items)}


async def create_kb(
    store: KnowledgeStore | PgKnowledgeStore,
    *,
    kb_id: str,
    name: str = "",
    description: str = "",
) -> dict[str, Any]:
    if not KB_ID_RE.fullmatch(kb_id):
        raise InvalidError("知识库 id 只能用小写字母/数字/./_/-，且以字母或数字开头", {"id": kb_id})
    if isinstance(store, PgKnowledgeStore):
        return await store.create_project(kb_id, name=name, description=description)
    async with write_lock(store.root):
        await manage.guard_project_write(store.root, kb_id)
        await archive.ensure_missing(await archive.checked_path(store.root, kb_id))
        kbs = await _load(store)
        await AsyncPath(store.root / kb_id).mkdir(parents=True, exist_ok=True)
        kbs[kb_id] = {
            "id": kb_id,
            "name": name.strip() or kb_id,
            "description": description.strip(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        await _save(store, kbs)
    return kbs[kb_id]


async def update_kb(
    store: KnowledgeStore | PgKnowledgeStore,
    kb_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    if isinstance(store, PgKnowledgeStore):
        return await store.update_project(kb_id, name=name, description=description)
    async with write_lock(store.root):
        if kb_id not in await _dirs(store):
            raise NotFoundError(f"知识库不存在: {kb_id}")
        await manage.guard_project_write(store.root, kb_id)
        kbs = await _load(store)
        entry = kbs.get(kb_id, {"id": kb_id, "name": kb_id, "description": ""})
        if name is not None:
            entry["name"] = name.strip() or kb_id
        if description is not None:
            entry["description"] = description.strip()
        kbs[kb_id] = entry
        await _save(store, kbs)
    return entry


async def _strict_registry(store: KnowledgeStore) -> tuple[bytes | None, dict[str, Any]]:
    raw = await archive.read_optional(_registry_path(store))
    if raw is None:
        return None, {"kbs": []}
    try:
        data = json.loads(raw)
        items = data["kbs"]
        if not isinstance(items, list):
            raise TypeError("kbs")
        ids = [item["id"] for item in items]
        if not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("ids")
        return raw, data
    except (TypeError, ValueError, KeyError) as exc:
        raise ConflictError("知识库登记文件无法读取") from exc


def _resolve(ids: set[str]) -> Callable[[str], str | None]:
    aliases: dict[str, str | None] = {}
    for node in ids:
        slug = node.rsplit("/", 1)[-1]
        aliases[slug] = None if slug in aliases else node
    return lambda value: value if value in ids else aliases.get(value)


def _rows(data: bytes, path: str) -> list[tuple[bytes, dict[str, Any] | None]]:
    result: list[tuple[bytes, dict[str, Any] | None]] = []
    for line in data.splitlines(keepends=True):
        if not line.strip():
            result.append((line, None))
            continue
        try:
            row = json.loads(line.decode("utf-8"))
            if not all(isinstance(row[key], str) for key in ("source", "target", "predicate")):
                raise ValueError("edge")
        except (TypeError, ValueError, KeyError) as exc:
            raise ConflictError("无法读取关系文件", {"path": path}) from exc
        result.append((line, row))
    return result


def _ends(row: dict[str, Any], resolve: Callable[[str], str | None]) -> list[str | None]:
    return [resolve(row["source"]), resolve(row["target"])]


async def _edge_bytes(store: KnowledgeStore) -> AsyncIterator[tuple[str, bytes]]:
    for path in await manage._edge_files(store):
        name = path.relative_to(store.root).as_posix()
        data = await archive.read_optional(await archive.checked_path(store.root, name))
        if data is not None:
            yield name, data


async def delete_kb(
    store: KnowledgeStore | PgKnowledgeStore, kb_id: str, *, actor: str = "ui"
) -> dict[str, Any]:
    """保存可校验的整库快照，再摘除活跃节点、关系和登记。"""
    if not KB_ID_RE.fullmatch(kb_id):
        raise InvalidError("知识库 id 不合法")
    if isinstance(store, PgKnowledgeStore):
        return await store.archive_project_kb(kb_id, actor=actor)
    async with write_lock(store.root):
        root = await archive.checked_path(store.root, kb_id)
        root_dir = AsyncPath(root)
        if await archive.path_kind(root) != "dir":
            raise NotFoundError(f"知识库不存在: {kb_id}")
        registry, data = await _strict_registry(store)
        entry = next((item for item in data["kbs"] if item["id"] == kb_id), None)
        dirs = [kb_id]
        files: dict[str, bytes] = {}
        node_ids: set[str] = set()
        # 在遍历下一层之前检查链接/重解析点，不读取库外的文件。
        pending_dirs = [root_dir]
        while pending_dirs:
            async for path in pending_dirs.pop().iterdir():
                name = path.relative_to(store.root).as_posix()
                real_path = await archive.checked_path(store.root, name)
                kind = await archive.path_kind(real_path)
                if kind == "dir" and path.name != "_edges.jsonl" and path.suffix != ".md":
                    dirs.append(name)
                    pending_dirs.append(path)
                elif kind == "file" and path.suffix == ".md":
                    node_id = name[:-3]
                    try:
                        await store.read(node_id)
                    except (OSError, ValueError) as exc:
                        raise ConflictError("无法读取库内节点", {"path": name}) from exc
                    files[name] = await path.read_bytes()
                    node_ids.add(node_id)
                elif kind == "file" and name == f"{kb_id}/_edges.jsonl":
                    files[name] = await path.read_bytes()
                else:
                    raise ConflictError("库内含无法识别的文件", {"path": name})
        ids = set(await store.list_ids())
        before, after = _resolve(ids), _resolve(ids - node_ids)
        captured: dict[str, list[dict[str, Any]]] = {}
        steps: list[archive.Step] = []
        async for name, original in _edge_bytes(store):
            kept = []
            removed = []
            for line, row in _rows(original, name):
                if row is None:
                    kept.append(line)
                    continue
                endpoints = _ends(row, before)
                if name in files or any(endpoint in node_ids for endpoint in endpoints):
                    removed.append({"line": line.decode(), "endpoints": endpoints})
                else:
                    if endpoints != _ends(row, after):
                        raise ConflictError("归档会改变现有关系的短别名", {"path": name})
                    kept.append(line)
            if removed:
                captured[name] = removed
                if name not in files:
                    steps.append(archive.Step(name, original, b"".join(kept)))
        archive_id = uuid.uuid4().hex
        prefix = f"{archive.ARCHIVES}/{archive_id}"
        folder = await archive.checked_path(store.root, f"{prefix}/snapshot.zip")
        block = await archive.checked_path(store.root, f"{archive.ARCHIVES}/blocked/{kb_id}")
        await archive.ensure_missing(block)
        await archive.make_archive_dirs(folder.parent, block.parent)
        header = {
            "id": kb_id,
            "archive_id": archive_id,
            "deleted_at": datetime.now(UTC).isoformat(),
            "name": str((entry or {}).get("name") or kb_id),
            "actor": actor,
            "archived_count": len(node_ids),
            "removed_edges": sum(map(len, captured.values())),
        }
        digest = await archive.save_bundle(
            folder, {"header": header, "entry": entry, "dirs": dirs, "edges": captured}, files
        )
        if entry is not None:
            data["kbs"].remove(entry)
            steps.append(archive.Step(REGISTRY_NAME, registry, archive.json_bytes(data)))
        steps.extend(archive.Step(name, content, None) for name, content in files.items())
        steps.extend(
            archive.Step(name, "dir", None) for name in sorted(dirs, key=len, reverse=True)
        )
        steps.extend(
            (
                archive.Step(block.relative_to(store.root).as_posix(), None, archive_id.encode()),
                archive.Step(
                    f"{prefix}/active.json",
                    None,
                    archive.json_bytes({"header": header, "sha256": digest}),
                ),
            )
        )
        await archive.execute(store.root, archive_id, steps)
        commit = await manage._git_commit(store.root, f"kb: 归档知识库 {kb_id}")
    return {**header, "commit": commit}


async def list_archives(store: KnowledgeStore | PgKnowledgeStore) -> dict[str, Any]:
    if isinstance(store, PgKnowledgeStore):
        return await store.list_archives()
    if not await AsyncPath(store.root).is_dir():
        return {"items": [], "total": 0}
    async with write_lock(store.root):
        directory = await archive.checked_path(store.root, f"{archive.ARCHIVES}/unused")
        items = []
        if await AsyncPath(directory.parent).is_dir():
            async for folder in AsyncPath(directory.parent).iterdir():
                if not archive.ARCHIVE_ID.fullmatch(folder.name):
                    continue
                path = await archive.checked_path(
                    store.root, f"{archive.ARCHIVES}/{folder.name}/active.json"
                )
                raw = await archive.read_optional(path)
                if raw is not None:
                    items.append(_archive_index(raw, folder.name)[0])
        items.sort(key=lambda item: item["deleted_at"], reverse=True)
        return {"items": items, "total": len(items)}


def _archive_index(raw: bytes, archive_id: str) -> tuple[dict[str, Any], str]:
    try:
        index = json.loads(raw)
        header = index["header"]
        digest = index["sha256"]
        if not isinstance(digest, str):
            raise TypeError("sha256")
        if (
            not isinstance(header, dict)
            or header["archive_id"] != archive_id
            or not KB_ID_RE.fullmatch(header["id"])
            or not all(isinstance(header[key], str) for key in ("name", "deleted_at"))
            or not all(
                type(header[key]) is int and header[key] >= 0
                for key in ("archived_count", "removed_edges")
            )
        ):
            raise ValueError("header")
    except (TypeError, KeyError, ValueError) as exc:
        raise ConflictError("知识库归档索引损坏") from exc
    return header, digest


async def restore_kb(store: KnowledgeStore | PgKnowledgeStore, archive_id: str) -> dict[str, Any]:
    if isinstance(store, PgKnowledgeStore):
        return await store.restore_project_kb(archive_id)
    if not archive.ARCHIVE_ID.fullmatch(archive_id):
        raise NotFoundError("知识库归档不存在")
    async with write_lock(store.root):
        prefix = f"{archive.ARCHIVES}/{archive_id}"
        active = await archive.checked_path(store.root, f"{prefix}/active.json")
        active_bytes = await archive.read_optional(active)
        if active_bytes is None:
            raise NotFoundError("知识库归档不存在")
        header, digest = _archive_index(active_bytes, archive_id)
        try:
            meta, files = await archive.load_bundle(active.with_name("snapshot.zip"), digest)
        except NotFoundError as exc:
            raise ConflictError("知识库归档快照缺失") from exc
        entry, dirs, captured = _archive_metadata(meta, header, files)
        kb_id = header["id"]
        await archive.ensure_missing(await archive.checked_path(store.root, kb_id))
        registry, data = await _strict_registry(store)
        if any(item["id"] == kb_id for item in data["kbs"]):
            raise ConflictError("已存在同名库登记", {"id": kb_id})
        ids = set(await store.list_ids())
        before = _resolve(ids)
        after = _resolve(ids | {name[:-3] for name in files if name.endswith(".md")})
        live_edges = {name: raw async for name, raw in _edge_bytes(store)}
        for name, raw in live_edges.items():
            for _, row in _rows(raw, name):
                if row is not None and _ends(row, before) != _ends(row, after):
                    raise ConflictError("恢复会改变现有关系的短别名", {"path": name})
        steps = [archive.Step(name, None, "dir") for name in sorted(dirs, key=len)]
        steps.extend(archive.Step(name, None, raw) for name, raw in files.items())
        for name, saved in captured.items():
            path = await archive.checked_path(store.root, name)
            if name not in files and not await AsyncPath(path.parent).is_dir():
                raise ConflictError("跨库关系所属目录已不存在", {"path": name})
            live = live_edges.get(name)
            current: dict[tuple[str, str, str], list[bytes]] = {}
            for line, row in _rows(live or b"", name):
                if row is not None:
                    source, target = _ends(row, after)
                    key = (source or row["source"], target or row["target"], row["predicate"])
                    current.setdefault(key, []).append(line.strip())
            additions = []
            for saved_row in saved:
                line = saved_row["line"].encode()
                _, row = _rows(line, name)[0]
                assert row is not None
                endpoints = _ends(row, after)
                if endpoints != saved_row["endpoints"]:
                    raise ConflictError("关系端点缺失或短别名变化", {"path": name})
                source, target = endpoints
                key = (source or row["source"], target or row["target"], row["predicate"])
                matching = current.get(key, [])
                if line.strip() in matching:
                    matching.remove(line.strip())
                elif matching:
                    raise ConflictError("跨库关系已有不同记录", {"path": name})
                else:
                    additions.append(line)
            if name not in files and additions:
                merged = live or b""
                for line in additions:
                    if merged and not merged.endswith(b"\n"):
                        merged += b"\n"
                    merged += line
                steps.append(archive.Step(name, live, merged))
        if entry is not None:
            data["kbs"].append(entry)
            steps.append(archive.Step(REGISTRY_NAME, registry, archive.json_bytes(data)))
        blocked = f"{archive.ARCHIVES}/blocked/{kb_id}"
        steps.extend(
            (
                archive.Step(blocked, archive_id.encode(), None),
                archive.Step(f"{prefix}/active.json", active_bytes, None),
            )
        )
        await archive.execute(store.root, archive_id, steps)
        commit = await manage._git_commit(store.root, f"kb: 恢复知识库 {kb_id}")
    return {
        "id": kb_id,
        "archive_id": archive_id,
        "restored_count": header["archived_count"],
        "restored_edges": header["removed_edges"],
        "commit": commit,
    }


def _archive_metadata(
    meta: dict[str, Any],
    header: dict[str, Any],
    files: dict[str, bytes],
) -> tuple[dict[str, Any] | None, list[str], dict[str, list[dict[str, Any]]]]:
    try:
        saved_header, entry, dirs, captured = (
            meta[key] for key in ("header", "entry", "dirs", "edges")
        )
        kb_id = header["id"]
        if not isinstance(dirs, list) or not isinstance(captured, dict):
            raise TypeError("manifest")
        local_edges = f"{kb_id}/_edges.jsonl"
        if (
            saved_header != header
            or kb_id not in dirs
            or len(set(dirs)) != len(dirs)
            or (entry is not None and entry["id"] != kb_id)
            or any(name != kb_id and not name.startswith(f"{kb_id}/") for name in dirs)
            or any(
                name != local_edges and not (name.startswith(f"{kb_id}/") and name.endswith(".md"))
                for name in files
            )
            or any(
                name.rpartition("/")[0] not in dirs
                for name in [*files, *[d for d in dirs if d != kb_id]]
            )
            or header["archived_count"] != sum(name.endswith(".md") for name in files)
        ):
            raise ValueError("manifest")
        for name, rows in captured.items():
            if not name.endswith("/_edges.jsonl") or (
                name.startswith(f"{kb_id}/") and name not in files
            ):
                raise ValueError("edge path")
            if not isinstance(rows, list):
                raise TypeError("edge rows")
            for row in rows:
                decoded = _rows(row["line"].encode(), name)
                ends = row["endpoints"]
                if (
                    len(decoded) != 1
                    or decoded[0][1] is None
                    or not isinstance(ends, list)
                    or len(ends) != 2
                    or any(end is not None and not isinstance(end, str) for end in ends)
                ):
                    raise ValueError("edge record")
        if header["removed_edges"] != sum(map(len, captured.values())):
            raise ValueError("edge count")
        if [
            line for line, row in _rows(files.get(local_edges, b""), local_edges) if row is not None
        ] != [row["line"].encode() for row in captured.get(local_edges, [])]:
            raise ValueError("local edge inventory")
    except (TypeError, KeyError, ValueError, AttributeError) as exc:
        raise ConflictError("知识库归档元数据损坏") from exc
    return entry, dirs, captured


async def graph(store: KnowledgeStore | PgKnowledgeStore, project: str) -> dict[str, Any]:
    """知识库子图：节点 + 已解析边 + 度数。用于管理台自绘，直接读真源。"""
    if isinstance(store, PgKnowledgeStore):
        if not await store.project_exists(project):
            raise NotFoundError(f"知识库不存在: {project}")
        records = await query.records(store, project, include_body=False)
        edge_records = await store.edges(project)
    else:
        if project not in await _dirs(store):
            raise NotFoundError(f"知识库不存在: {project}")
        records = await query.records(store, project, include_body=False)
        edge_records = await _edges(store, project)
    ids = {record.id for record in records}
    slug_index: dict[str, list[str]] = {}
    for node_id in ids:
        slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

    def resolve(reference: str) -> str | None:
        if reference in ids:
            return reference
        candidates = slug_index.get(reference, [])
        return candidates[0] if len(candidates) == 1 else None

    degree: dict[str, int] = dict.fromkeys(ids, 0)
    edges: list[dict[str, str]] = []
    unresolved = 0
    for record in edge_records:
        source = resolve(str(record["source"]))
        target = resolve(str(record["target"]))
        if source is None or target is None:
            unresolved += 1
            continue
        edges.append({"source": source, "target": target, "predicate": str(record["predicate"])})
        degree[source] += 1
        degree[target] += 1

    nodes = [
        {
            "id": record.id,
            "title": record.node.title,
            "kind": record.node.kind.value,
            "tier": record.node.tier.value,
            "entity_kind": record.node.entity_kind.value if record.node.entity_kind else None,
            "tags": record.node.tags,
            "degree": degree.get(record.id, 0),
            "updated_at": record.node.updated_at.isoformat(),
        }
        for record in records
    ]
    return {
        "project": project,
        "nodes": sorted(nodes, key=lambda item: (-item["degree"], item["id"])),
        "edges": edges,
        "unresolved_edges": unresolved,
    }
