"""分节与会话渲染。"""

from __future__ import annotations

import json

from memhub.worker.render import render_jsonl
from memhub.worker.split import split_markdown


def test_split_keeps_document_when_small() -> None:
    assert split_markdown("# a\n\nbody") == ["# a\n\nbody"]


def test_split_by_headings_under_limit() -> None:
    sections = "\n\n".join(f"## section {index}\n\n{'x' * 400}" for index in range(10))
    chunks = split_markdown(sections, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert all("## section" in chunk for chunk in chunks)


def test_split_hard_cuts_oversize_section() -> None:
    chunks = split_markdown("## big\n\n" + "y" * 2500, max_chars=1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) >= 2500


def test_render_jsonl_keeps_dialogue_and_skips_tool_results() -> None:
    events = [
        {"type": "user", "message": {"role": "user", "content": "帮我看看 502"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "根因是上游超时"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "curl x"}},
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "noise" * 1000}],
            },
        },
        {"type": "summary", "summary": "定位 Proxy 502"},
    ]
    text = render_jsonl("\n".join(json.dumps(event) for event in events))
    assert "[user] 帮我看看 502" in text
    assert "根因是上游超时" in text
    assert "[tool Bash]" in text
    assert "noise" not in text
    assert "[summary] 定位 Proxy 502" in text
