"""把会话原始文件转成可抽取的文本。

Claude Code 的 session 是 JSONL，事件繁多且工具输出很长；直接喂给模型会淹没重点。
会话证据只保留可编号的对话文本；文档路径继续使用旧的展示格式。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

MAX_TOOL_INPUT = 300
DEFAULT_BLOCK_CHARS = 6000


@dataclass(frozen=True, slots=True)
class SessionBlock:
    id: str
    role: str
    text: str


def render_session_blocks(
    text: str, *, max_block_chars: int = DEFAULT_BLOCK_CHARS
) -> list[SessionBlock]:
    """只编号真实对话中的文本；不把解析失败的行当作正文。"""
    return _number_blocks(_dialogue_blocks(text), max_block_chars)


def _dialogue_blocks(text: str) -> Iterator[tuple[str, str]]:
    # JSONL 只在换行字节分隔；文本里的 Unicode 行分隔符不是事件边界。
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(event, dict) or event.get("isMeta") or event.get("isCompactSummary"):
            continue
        role = event.get("type")
        if role not in ("user", "assistant"):
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("isMeta"):
            continue
        if message.get("role", role) != role:
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield role, content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    value = block.get("text")
                    if isinstance(value, str):
                        yield role, value


def render_plaintext_blocks(
    text: str, *, max_block_chars: int = DEFAULT_BLOCK_CHARS
) -> list[SessionBlock]:
    """仅用于显式的纯文本会话，不是 JSONL 解析回退。"""
    paragraphs = re.split(r"\r?\n[^\S\r\n]*\r?\n", text)
    return _number_blocks((("text", part) for part in paragraphs), max_block_chars)


def _number_blocks(pieces: Iterable[tuple[str, str]], limit: int) -> list[SessionBlock]:
    if limit <= 0:
        raise ValueError("max_block_chars 必须为正")
    result: list[SessionBlock] = []
    ordinal = 0
    for role, raw in pieces:
        text = raw.strip()
        if not text:
            continue
        ordinal += 1
        block_id = f"b{ordinal:04d}"
        if len(text) <= limit:
            result.append(SessionBlock(block_id, role, text))
            continue
        for part, start in enumerate(range(0, len(text), limit), 1):
            value = text[start : start + limit]
            if value.strip():
                result.append(SessionBlock(f"{block_id}.{part}", role, value))
    return result


def truncate_blocks(blocks: Sequence[SessionBlock], max_chars: int) -> list[SessionBlock]:
    """按正文字符总量截取前缀，保留原编号，不将遗漏文本变成证据。"""
    prefix: list[SessionBlock] = []
    for block in blocks:
        if max_chars <= 0:
            break
        if len(block.text) > max_chars:
            if (value := block.text[:max_chars]).strip():
                prefix.append(replace(block, text=value))
            break
        prefix.append(block)
        max_chars -= len(block.text)
    return prefix


@dataclass(frozen=True, slots=True)
class SessionWindow:
    text: str
    blocks: tuple[SessionBlock, ...]
    context: SessionBlock | None


def _block_line(block: SessionBlock, label: str) -> str:
    # 单行 JSON 字符串让正文无法伪造分块标记，引用按解码后的原文匹配。
    text = json.dumps(block.text, ensure_ascii=False)
    return f"[{block.id} {block.role} {label}] {text}"


def _fit_blocks(blocks: Sequence[SessionBlock], max_chars: int) -> Iterator[SessionBlock]:
    for block in blocks:
        if len(_block_line(block, "new")) <= max_chars:
            yield block
            continue

        # 仅超出当前配置的块需要再切分；预算计入编号、标签与 JSON 转义。
        start = 0
        part = 0
        while start < len(block.text):
            part += 1
            fragment = replace(block, id=f"{block.id}.{part}", text="")
            budget = max_chars - len(_block_line(fragment, "new"))
            end = start
            while end < len(block.text):
                size = len(json.dumps(block.text[end], ensure_ascii=False)) - 2
                if size > budget:
                    break
                budget -= size
                end += 1
            if end == start:
                raise ValueError("max_chars 无法容纳会话块及其标签")
            value = block.text[start:end]
            if value.strip():
                yield replace(fragment, text=value)
            start = end


def session_windows(blocks: Sequence[SessionBlock], max_chars: int) -> Iterator[SessionWindow]:
    """每窗至少有一个新块；至多携带上窗最后一个块，且上下文不超过预算的 1/3。"""
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正")
    # 调用方不能提供重复编号，否则相同引用有多个可能对应的原文。
    if len({block.id for block in blocks}) != len(blocks):
        raise ValueError("会话块的编号必须唯一")

    current: list[SessionBlock] = []
    lines: list[str] = []
    used = 0
    context: SessionBlock | None = None
    for block in _fit_blocks(blocks, max_chars):
        line = _block_line(block, "new")
        if lines and used + 1 + len(line) > max_chars:
            yield SessionWindow("\n".join(lines), tuple(current), context)
            previous = current[-1]
            context_line = _block_line(previous, "context")
            current, lines, used, context = [], [], 0, None
            if len(context_line) + 1 <= min(max_chars // 3, max_chars - len(line)):
                context = previous
                lines.append(context_line)
                used = len(context_line)
        used += bool(lines) + len(line)
        current.append(block)
        lines.append(line)
    if current:
        yield SessionWindow("\n".join(lines), tuple(current), context)


def render_jsonl(text: str) -> str:
    """只返回渲染文本；调用方不关心是否解析到事件时用它。"""
    rendered, _events = render_jsonl_events(text)
    return rendered


def render_jsonl_events(text: str) -> tuple[str, int]:
    """返回 (渲染文本, 解析成功的事件数)。

    区分两种「渲染为空」：事件数为 0 说明这段可能从事件中间切出来（增量边界），
    调用方可以退回原文；解析到了事件但渲染为空是另一回事（例如整份只有技能注入
    和工具结果），此时绝不能退回原文——那等于把注入文档整段喂给模型。
    """
    lines: list[str] = []
    parsed = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed += 1

        # 技能文档等注入也可能使用 user 角色；isMeta 标记的事件不是实际对话。
        # 在读取正文之前过滤，避免把技能手册当成用户提供的知识。
        if event.get("isMeta"):
            continue

        event_type = event.get("type")
        if event_type == "summary":
            summary = event.get("summary")
            if isinstance(summary, str) and summary.strip():
                lines.append(f"[summary] {summary.strip()}")
            continue
        if event_type not in {"user", "assistant"}:
            continue

        message = event.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role") or event_type
        content = message.get("content")

        if isinstance(content, str):
            if content.strip():
                lines.append(f"[{role}] {content.strip()}")
            continue
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_value = block.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    lines.append(f"[{role}] {text_value.strip()}")
            elif block_type == "tool_use":
                name = block.get("name", "?")
                payload = json.dumps(block.get("input", {}), ensure_ascii=False)
                lines.append(f"[tool {name}] {payload[:MAX_TOOL_INPUT]}")
            # tool_result 一律丢弃：它们是命令输出，属于噪音。
    return "\n\n".join(lines), parsed
