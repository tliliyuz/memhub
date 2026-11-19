"""知识库（project）目录与子图（全异步 IO）。

真源按 `<root>/<project>/...` 隔离，这里的 project 就是「知识库」：`sdp-tag`、
`memory-hub` 各自一批节点，互不混杂。本模块只做两件事：

- 维护知识库元数据（`<root>/.kbs.json`：显示名、描述）；目录存在但没登记的
  知识库按目录名兜底展示，保证手工放进来的库也能看到。
- 按知识库导出子图（节点 + 解析后的边 + 度数），给管理台画图用；投影
  `kg.json` 仍是全局的，这里不读写它。

读写都走 `manage.write_lock`，与节点写操作互斥。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anyio import Path as AsyncPath

from memhub.kb import query
from memhub.kb.manage import InvalidError, NotFoundError, write_lock
from memhub.kb.store import KnowledgeStore

REGISTRY_NAME = ".kbs.json"
KB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


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


async def exists(store: KnowledgeStore, kb_id: str) -> bool:
    """轻量存在性判断：真源根下一级目录即知识库（与 `_dirs` 的判定一致）。

    不给上传路径用 `list_kbs`：它会逐库扫全部节点，只为判断一个 id 不值当。
    """
    if kb_id.startswith(("_", ".")):
        return False
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


async def list_kbs(store: KnowledgeStore) -> dict[str, Any]:
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
    store: KnowledgeStore, *, kb_id: str, name: str = "", description: str = ""
) -> dict[str, Any]:
    if not KB_ID_RE.match(kb_id):
        raise InvalidError("知识库 id 只能用小写字母/数字/./_/-，且以字母或数字开头", {"id": kb_id})
    if await AsyncPath(store.root / kb_id).is_dir():
        raise InvalidError(f"知识库已存在: {kb_id}", {"id": kb_id})
    async with write_lock(store.root):
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
    store: KnowledgeStore, kb_id: str, *, name: str | None = None, description: str | None = None
) -> dict[str, Any]:
    if kb_id not in await _dirs(store):
        raise NotFoundError(f"知识库不存在: {kb_id}")
    async with write_lock(store.root):
        kbs = await _load(store)
        entry = kbs.get(kb_id, {"id": kb_id, "name": kb_id, "description": ""})
        if name is not None:
            entry["name"] = name.strip() or kb_id
        if description is not None:
            entry["description"] = description.strip()
        kbs[kb_id] = entry
        await _save(store, kbs)
    return entry


async def graph(store: KnowledgeStore, project: str) -> dict[str, Any]:
    """知识库子图：节点 + 已解析边 + 度数。用于管理台自绘，不碰 kg.json。"""
    if project not in await _dirs(store):
        raise NotFoundError(f"知识库不存在: {project}")
    records = await query.records(store, project)
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
    for record in await _edges(store, project):
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
