"""prompt profile 加载与渲染。"""

from __future__ import annotations

from pathlib import Path

from anyio import Path as AsyncPath

PROMPT_DIR = Path(__file__).parents[3] / "prompts"
PROFILES = {"wiki", "sessions", "docs", "memory"}


async def load_profile(name: str, root: Path | None = None) -> str:
    if name not in PROFILES:
        raise ValueError(f"未知 profile: {name}")
    path = (root or PROMPT_DIR) / f"{name}.md"
    return await AsyncPath(path).read_text(encoding="utf-8")


def render(template: str, *, path: str, text: str, memory: str = "") -> str:
    # 不能用 str.format：模板里的 JSON 示例含大量花括号。
    return template.replace("{path}", path).replace("{text}", text).replace("{memory}", memory)


def render_nodes(template: str, *, nodes: str) -> str:
    return template.replace("{nodes}", nodes)
