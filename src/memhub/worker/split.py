"""按标题分节，保证单次 LLM 调用不触发输出截断。

实测 semantica 的单页抽取在约 6000 字符输出处会被截断，因此输入侧必须主动切分；
这里的上限按输入字符算，输出长度由 prompt 约束（每节知识条目数量有限）。
"""

from __future__ import annotations

import re

HEADING_RE = re.compile(r"^#{1,3}\s", re.MULTILINE)


def _hard_cut(block: str, max_chars: int) -> list[str]:
    """单个块仍然超限时按段落、再按字符硬切。"""
    paragraphs = [part for part in block.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def split_markdown(text: str, max_chars: int = 12000) -> list[str]:
    """返回非空块列表；每块不超过 max_chars，标题保留在块内。"""
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正")
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]

    starts = [match.start() for match in HEADING_RE.finditer(stripped)]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    sections = [
        stripped[start : starts[index + 1] if index + 1 < len(starts) else len(stripped)]
        for index, start in enumerate(starts)
    ]

    chunks: list[str] = []
    current = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_cut(section, max_chars))
            continue
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = section
    if current:
        chunks.append(current)
    return chunks
