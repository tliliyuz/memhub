"""分节与会话渲染。"""

from __future__ import annotations

import json

import pytest

from memhub.worker import render
from memhub.worker.render import render_jsonl, render_jsonl_events
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


@pytest.mark.parametrize("block_content", [False, True])
def test_render_jsonl_skips_meta_injections(block_content: bool) -> None:
    """合成样本：同为 user 角色，带 isMeta 的注入不能冒充实际对话。"""
    injection = "合成技能文档：内部注入，不是实际对话。" * 500
    events = [
        {"type": "user", "isMeta": False, "message": {"role": "user", "content": "hi"}},
        {
            "type": "user",
            "isMeta": True,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": injection}] if block_content else injection,
            },
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "收到"}]},
        },
    ]
    text = render_jsonl("\n".join(json.dumps(event) for event in events))
    assert "[user] hi" in text
    assert "收到" in text
    assert "合成技能文档" not in text


def test_render_jsonl_distinguishes_filtered_events_from_unparseable_input() -> None:
    event = {"type": "user", "isMeta": True, "message": {"content": "合成注入"}}
    assert render_jsonl_events(json.dumps(event)) == ("", 1)
    assert render_jsonl_events("invalid fragment") == ("", 0)


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


def test_session_blocks_filter_noise_and_keep_stable_dialogue_ids() -> None:
    lines = [
        json.dumps({"type": "summary", "summary": "synthetic summary"}),
        'truncated {"type": "user", "content": "synthetic fragment"}',
        json.dumps({"type": "user", "isMeta": True, "message": {"content": "synthetic meta"}}),
        json.dumps(
            {
                "type": "user",
                "isCompactSummary": True,
                "message": {"content": "synthetic compact"},
            }
        ),
        json.dumps({"type": "user", "message": {"content": "   Synthetic decision.  "}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "synthetic tool", "input": {"a": 2}},
                        {"type": "text", "text": "Verified the synthetic fixture."},
                        {"type": "thinking", "thinking": "synthetic thinking"},
                        {"type": "text", "text": "Kept configuration A."},
                        {"type": "tool_result", "content": "synthetic tool result"},
                    ]
                },
            }
        ),
        json.dumps({"type": "user", "message": {"role": "tool", "content": "wrong role"}}),
        json.dumps({"type": ["user"], "message": {"content": "malformed type"}}),
    ]
    blocks = render.render_session_blocks("\n".join(lines))
    assert [(block.id, block.role, block.text) for block in blocks] == [
        ("b0001", "user", "Synthetic decision."),
        ("b0002", "assistant", "Verified the synthetic fixture."),
        ("b0003", "assistant", "Kept configuration A."),
    ]
    assert render.render_session_blocks("\n".join(lines[3:])) == blocks
    assert render.render_session_blocks(lines[1]) == []


def test_plaintext_session_blocks_keep_paragraphs_and_truncate_by_content() -> None:
    blocks = render.render_plaintext_blocks("  First\r\nline.\r\n \r\nSecond item. \n")
    assert [(block.id, block.role, block.text) for block in blocks] == [
        ("b0001", "text", "First\r\nline."),
        ("b0002", "text", "Second item."),
    ]
    clipped = render.truncate_blocks(blocks, len(blocks[0].text) + 6)
    assert [(block.id, block.text) for block in clipped] == [
        ("b0001", "First\r\nline."),
        ("b0002", "Second"),
    ]
    assert render.truncate_blocks(blocks, 0) == []
