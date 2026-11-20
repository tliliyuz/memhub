"""markdown 真源读写（全异步 IO）。

一个节点 = 一个文件，路径 `<root>/<project>/<kind>/<slug>.md`；id 即相对路径去扩展名。
写入采用临时文件 + 原子替换；关系按项目追加到 `_edges.jsonl`（去重、整体重写）。
文件 IO 全部走 anyio 的异步 Path，不阻塞事件循环；`frontmatter` 解析是纯 CPU 操作。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import frontmatter
from anyio import Path as AsyncPath

from memhub.contract import Edge, NodeFrontmatter

# 删除是软删：原文件移到 `<root>/_trash/<时间戳>/<原 id>.md`。
# manage 的删除/恢复与这里的 list_ids 共用同一个名字。
TRASH_DIR = "_trash"


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, node_id: str) -> Path:
        return self.root / f"{node_id}.md"

    async def exists(self, node_id: str) -> bool:
        return await AsyncPath(self.path_for(node_id)).is_file()

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        text = await AsyncPath(self.path_for(node_id)).read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        metadata = dict(post.metadata)
        metadata["id"] = node_id
        node = NodeFrontmatter.model_validate(metadata)
        return node, post.content

    async def write(self, node_id: str, node: NodeFrontmatter, body: str) -> Path:
        path = self.path_for(node_id)
        await AsyncPath(path.parent).mkdir(parents=True, exist_ok=True)
        metadata = node.model_dump(mode="json", exclude_none=True)
        metadata["id"] = node_id
        text = frontmatter.dumps(frontmatter.Post(body.rstrip() + "\n", **metadata))
        await _atomic_write(path, text + "\n")
        return path

    async def list_ids(self, project: str | None = None) -> list[str]:
        base = self.root / project if project else self.root
        if not await AsyncPath(base).is_dir():
            return []
        ids: list[str] = []
        async for path in AsyncPath(base).rglob("*.md"):
            relative = Path(path).relative_to(self.root)
            # 回收站里的文件仍是 markdown，但不是节点：不跳过的话删除过的节点会以
            # `_trash/<时间戳>/<原 id>` 的伪节点身份重新出现在投影和图谱里。
            if relative.parts[0] == TRASH_DIR:
                continue
            ids.append(relative.with_suffix("").as_posix())
        return sorted(ids)

    def edges_path(self, project: str) -> Path:
        return self.root / project / "_edges.jsonl"

    async def append_edges(self, project: str, edges: list[Edge], source_doc: str) -> int:
        path = self.edges_path(project)
        await AsyncPath(path.parent).mkdir(parents=True, exist_ok=True)
        existing: dict[tuple[str, str, str], dict[str, object]] = {}
        if await AsyncPath(path).is_file():
            text = await AsyncPath(path).read_text(encoding="utf-8")
            for line in text.splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                key = (str(record["source"]), str(record["predicate"]), str(record["target"]))
                existing[key] = record
        added = 0
        for edge in edges:
            key = (edge.source, edge.predicate.value, edge.target)
            if key in existing:
                continue
            entry: dict[str, object] = {
                "source": edge.source,
                "predicate": edge.predicate.value,
                "target": edge.target,
                "source_doc": source_doc,
            }
            existing[key] = entry
            added += 1
        text = "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in existing.values()
        )
        await _atomic_write(path, text)
        return added


async def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        async with await AsyncPath(tmp).open("w", encoding="utf-8", newline="\n") as handle:
            await handle.write(text)
        await AsyncPath(tmp).replace(path)
    except BaseException:
        try:
            await AsyncPath(tmp).unlink()
        except OSError:
            pass
        raise
