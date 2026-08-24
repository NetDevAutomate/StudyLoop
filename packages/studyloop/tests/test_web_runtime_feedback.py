"""Fast tests for web runtime feedback helpers and CLI output."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.web.runtime_feedback import (
    build_web_access_info,
    emit_lan_credential_lines,
    format_web_access_lines,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_build_web_access_info_filters_wildcard_lan_hosts() -> None:
    info = build_web_access_info(
        bind_host="0.0.0.0",
        port=8567,
        lan_enabled=True,
        lan_hosts=("0.0.0.0", "127.0.0.1", "192.168.1.44", "192.168.1.44"),
    )

    assert info.local_url == "http://127.0.0.1:8567"
    assert info.lan_urls == ("http://192.168.1.44:8567",)
    assert info.bind_url == "http://0.0.0.0:8567"


def test_format_web_access_lines_uses_client_urls_for_lan() -> None:
    info = build_web_access_info(
        bind_host="0.0.0.0",
        port=8567,
        lan_enabled=True,
        lan_hosts=("10.0.0.9",),
        path="/session",
    )

    lines = format_web_access_lines(info)

    assert "Local: http://127.0.0.1:8567/session" in "\n".join(lines)
    assert "LAN:   http://10.0.0.9:8567/session" in "\n".join(lines)
    assert "no transport confidentiality" in "\n".join(lines).casefold()
    assert "offline" in "\n".join(lines).casefold()


def test_format_lan_credentials_shows_generated_password_only() -> None:
    generated: list[str] = []
    configured: list[str] = []
    emit_lan_credential_lines(
        username="study",
        generated_password="generated-secret",  # pragma: allowlist secret
        emit=generated.append,
    )
    emit_lan_credential_lines(
        username="study",
        generated_password=None,
        emit=configured.append,
    )

    assert "generated-secret" in "\n".join(generated)
    assert "stored-secret" not in "\n".join(configured)
    assert "configured; not shown" in "\n".join(configured)


def test_web_help_distinguishes_local_default_from_lan_mode() -> None:
    result = CliRunner().invoke(cli, ["web", "--help"])
    output = " ".join(result.output.casefold().split())

    assert result.exit_code == 0
    assert "on this computer by default" in output
    assert "pass --lan" in output
    assert "tablet or laptop on the same network" in output
    assert "accessible from any device on the network" not in output


def test_web_lan_output_uses_client_urls_without_echoing_configured_passwords(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    uvicorn = pytest.importorskip("uvicorn")
    from studyloop.learner_credentials import verify_password

    config = tmp_path / "config.yaml"
    config.write_text("lan_username: study\nlan_password: stored-secret\n")
    app_kwargs: dict[str, object] = {}

    def capture_app(**kwargs):
        app_kwargs.update(kwargs)
        return object()

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.44",))
    monkeypatch.setattr("studyloop.web.app.create_app", capture_app)
    monkeypatch.setattr(uvicorn.Server, "run", lambda *_, **__: None)

    result = CliRunner().invoke(cli, ["web", "--lan"])

    assert result.exit_code == 0, result.output
    assert "Local: http://127.0.0.1:8567" in result.output
    assert "LAN:   http://192.168.1.44:8567" in result.output
    assert "Study PWA at http://0.0.0.0:8567" not in result.output
    assert "configured; not shown" in result.output
    assert "stored-secret" not in result.output
    assert "stored-secret" not in config.read_text()
    assert "lan_password:" not in config.read_text()
    assert verify_password("stored-secret", str(app_kwargs["password_verifier"]))
    assert "password" not in app_kwargs
