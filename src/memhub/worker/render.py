"""把会话原始文件转成可抽取的文本。

Claude Code 的 session 是 JSONL，事件繁多且工具输出很长；直接喂给模型会淹没重点。
这里只保留对话文本与工具调用的简短标记，并丢掉 `isMeta` 注入。
"""

from __future__ import annotations

import json

MAX_TOOL_INPUT = 300


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
