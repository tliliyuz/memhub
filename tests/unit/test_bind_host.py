"""ingest-api 绑定地址：默认回环，非回环必须显式放行。"""

from __future__ import annotations

import pytest

from memhub.cli.main import resolve_bind_host


def test_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_HTTP_HOST", raising=False)
    assert resolve_bind_host() == "127.0.0.1"


def test_reads_env_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_HTTP_HOST", "localhost")
    assert resolve_bind_host() == "localhost"


def test_blank_env_falls_back_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_HTTP_HOST", "  ")
    assert resolve_bind_host() == "127.0.0.1"


def test_non_loopback_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MEMHUB_HTTP_HOST", "0.0.0.0")
    with pytest.raises(SystemExit) as excinfo:
        resolve_bind_host()
    assert excinfo.value.code == 2
    assert "非回环" in capsys.readouterr().err
    assert resolve_bind_host(allow_non_loopback=True) == "0.0.0.0"
