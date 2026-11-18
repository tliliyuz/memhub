"""markdown 真源读写。

一个节点 = 一个文件，路径 `<root>/<project>/<kind>/<slug>.md`；id 即相对路径去扩展名。
写入采用临时文件 + 原子替换；关系按项目追加到 `_edges.jsonl`（去重、整体重写）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import frontmatter

from memhub.contract import Edge, NodeFrontmatter


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, node_id: str) -> Path:
        return self.root / f"{node_id}.md"

    def exists(self, node_id: str) -> bool:
        return self.path_for(node_id).is_file()

    def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        post = frontmatter.load(self.path_for(node_id))
        metadata = dict(post.metadata)
        metadata["id"] = node_id
        node = NodeFrontmatter.model_validate(metadata)
        return node, post.content

    def write(self, node_id: str, node: NodeFrontmatter, body: str) -> Path:
        path = self.path_for(node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = node.model_dump(mode="json", exclude_none=True)
        metadata["id"] = node_id
        text = frontmatter.dumps(frontmatter.Post(body.rstrip() + "\n", **metadata))
        _atomic_write(path, text + "\n")
        return path

    def list_ids(self, project: str | None = None) -> list[str]:
        base = self.root / project if project else self.root
        if not base.is_dir():
            return []
        ids: list[str] = []
        for path in base.rglob("*.md"):
            ids.append(path.relative_to(self.root).with_suffix("").as_posix())
        return sorted(ids)

    def edges_path(self, project: str) -> Path:
        return self.root / project / "_edges.jsonl"

    def append_edges(self, project: str, edges: list[Edge], source_doc: str) -> int:
        path = self.edges_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[tuple[str, str, str], dict[str, object]] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
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
        _atomic_write(path, text)
        return added


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
