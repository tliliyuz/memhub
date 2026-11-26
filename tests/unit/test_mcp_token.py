"""`memhub mcp token` 本地令牌生成器的输出契约。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from memhub.cli.main import main
from memhub.mcp.auth import load_grants

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43,128}")


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(["mcp", "token", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_json_output_contains_valid_token_and_grant(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(
        capsys,
        "--name",
        "claude-code-laptop",
        "--projects",
        "memhub",
        "--scope",
        "read",
        "--days",
        "90",
        "--json",
    )
    assert code == 0
    payload = json.loads(out)
    token = payload["token"]
    grant = payload["grant"]
    assert TOKEN_RE.fullmatch(token)
    assert grant["sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert grant["scope"] == "mcp:read"
    assert grant["projects"] == ["memhub"]
    assert grant["name"] == "claude-code-laptop"
    validated = load_grants(json.dumps([grant]))[grant["sha256"]]
    assert validated.expires_at.utcoffset() == timedelta(0)
    assert abs((validated.expires_at - datetime.now(UTC)) - timedelta(days=90)) < timedelta(
        minutes=1
    )
    assert token not in err
    assert validated.scope == "mcp:read"
    assert validated.projects == frozenset({"memhub"})


def test_machine_output_omits_name_when_absent(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "--projects", "memhub", "--json")
    assert code == 0
    assert json.loads(out)["grant"]["name"] is None


def test_write_scope_and_multiple_projects(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "--projects", "memhub,other", "--scope", "write", "--json")
    assert code == 0
    assert json.loads(out)["grant"]["scope"] == "mcp:write"
    assert json.loads(out)["grant"]["projects"] == ["memhub", "other"]


def test_human_output_shows_token_once_with_paste_ready_grant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(capsys, "--name", "smoke", "--projects", "memhub")
    assert code == 0
    token = next(match.group(0) for match in TOKEN_RE.finditer(out))
    assert out.count(token) == 1
    assert "MEMHUB_MCP_GRANTS" in out
    assert "不要" in err
    assert token not in err


def test_tokens_are_random(capsys: pytest.CaptureFixture[str]) -> None:
    _, first, _ = _run(capsys, "--projects", "memhub", "--json")
    _, second, _ = _run(capsys, "--projects", "memhub", "--json")
    assert json.loads(first)["token"] != json.loads(second)["token"]


def test_invalid_project_fails_without_printing_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(capsys, "--projects", "Not A Project!", "--json")
    assert code == 2
    assert out == ""
    assert "project" in err.lower()
