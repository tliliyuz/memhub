"""LLM 抽取的输出结构。

模型只允许产出这里定义的形状；校验失败即视为该次抽取失败，不做容错猜测。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memhub.contract import EntityKind, Kind, Predicate

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_slug(raw: str) -> str:
    """把模型给出的 slug 收敛到 kebab-case；无法收敛时返回空串。"""
    slug = raw.strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug if SLUG_RE.match(slug) else ""


class ExtractedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    entity_kind: EntityKind | None = None
    title: str = Field(min_length=1)
    slug: str
    body: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def check_identity(self) -> ExtractedNode:
        if self.kind is Kind.ENTITY and self.entity_kind is None:
            raise ValueError("kind=entity 时必须提供 entity_kind")
        if not SLUG_RE.match(self.slug):
            raise ValueError(f"非法 slug: {self.slug}")
        return self


class ExtractedEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    predicate: Predicate
    target: str


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)

    def dedupe(self) -> Extraction:
        nodes: dict[str, ExtractedNode] = {}
        for node in self.nodes:
            existing = nodes.get(node.slug)
            if existing is None:
                nodes[node.slug] = node
                continue
            merged_tags = sorted(set(existing.tags) | set(node.tags))
            nodes[node.slug] = existing.model_copy(update={"tags": merged_tags})
        edges: dict[tuple[str, str, str], ExtractedEdge] = {}
        for edge in self.edges:
            edges[(edge.source, edge.predicate.value, edge.target)] = edge
        return Extraction(nodes=list(nodes.values()), edges=list(edges.values()))
