from __future__ import annotations

import pytest

from memhub.cli.main import _serve_env


def test_serve_env_fills_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("PYTHONUTF8", "PYTHONIOENCODING", "SEMANTICA_ALLOW_ANONYMOUS"):
        monkeypatch.delenv(key, raising=False)
    env = _serve_env()
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["SEMANTICA_ALLOW_ANONYMOUS"] == "true"


def test_serve_env_keeps_explicit_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTICA_ALLOW_ANONYMOUS", "false")
    assert _serve_env()["SEMANTICA_ALLOW_ANONYMOUS"] == "false"
