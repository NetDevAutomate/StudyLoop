"""Tests for the `studyctl web` CLI command (_web.py).

Tests the Click command itself — not the FastAPI application. Uses mocked
uvicorn to verify the command wires up host/port correctly without needing
fastapi installed.

No conftest.py (pluggy conflict) — all fixtures are inline.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from studyctl.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_uvicorn():
    """A mock uvicorn module that records run() calls."""
    mod = types.ModuleType("uvicorn")
    calls = []

    def fake_run(app, host, port, workers, log_level):
        calls.append({"host": host, "port": port, "workers": workers})

    mod.run = fake_run
    mod._calls = calls
    return mod


@pytest.fixture
def mock_web_app_module():
    """Pre-load a mock studyctl.web.app module so the import in _web.py succeeds
    even without fastapi installed."""
    fake_app_mod = types.ModuleType("studyctl.web.app")
    fake_app_mod.create_app = MagicMock(return_value=MagicMock())
    return fake_app_mod


class TestWebCliNoUvicorn:
    def test_shows_install_hint_when_uvicorn_missing(self, runner: CliRunner) -> None:
        """web command exits cleanly with install hint when uvicorn is absent."""
        with patch.dict(sys.modules, {"uvicorn": None}):
            result = runner.invoke(cli, ["web"])
        assert result.exit_code == 0
        assert "web server requires FastAPI" in result.output

    def test_web_help_always_works(self, runner: CliRunner) -> None:
        """web --help exits 0 regardless of optional deps."""
        result = runner.invoke(cli, ["web", "--help"])
        assert result.exit_code == 0
        assert "Port" in result.output or "port" in result.output


class TestWebCliLocalhost:
    def _run_web(self, runner, mock_uvicorn, mock_web_app_module, extra_args=None):
        """Helper to invoke `studyctl web` with all heavy deps mocked."""
        extra_args = extra_args or []
        with (
            patch.dict(
                sys.modules,
                {"uvicorn": mock_uvicorn, "studyctl.web.app": mock_web_app_module},
            ),
            patch("studyctl.settings.load_settings") as mock_settings,
        ):
            mock_settings.return_value.lan_username = "study"
            mock_settings.return_value.lan_password = ""
            mock_settings.return_value.ttyd_port = 7681
            return runner.invoke(cli, ["web", *extra_args])

    def test_binds_to_localhost_by_default(
        self, runner: CliRunner, mock_uvicorn, mock_web_app_module
    ) -> None:
        """web without --lan binds to 127.0.0.1."""
        result = self._run_web(runner, mock_uvicorn, mock_web_app_module)
        assert result.exit_code == 0
        assert mock_uvicorn._calls[0]["host"] == "127.0.0.1"

    def test_uses_custom_port(self, runner: CliRunner, mock_uvicorn, mock_web_app_module) -> None:
        """web --port N passes that port to uvicorn."""
        result = self._run_web(runner, mock_uvicorn, mock_web_app_module, ["--port", "9000"])
        assert result.exit_code == 0
        assert mock_uvicorn._calls[0]["port"] == 9000

    def test_shows_local_url_in_output(
        self, runner: CliRunner, mock_uvicorn, mock_web_app_module
    ) -> None:
        """web prints the local access URL."""
        result = self._run_web(runner, mock_uvicorn, mock_web_app_module)
        assert result.exit_code == 0
        assert "http://" in result.output


class TestWebCliLan:
    def test_lan_flag_binds_to_all_interfaces(
        self, runner: CliRunner, mock_uvicorn, mock_web_app_module
    ) -> None:
        """web --lan binds to 0.0.0.0."""
        with (
            patch.dict(
                sys.modules,
                {"uvicorn": mock_uvicorn, "studyctl.web.app": mock_web_app_module},
            ),
            patch("studyctl.settings.load_settings") as mock_settings,
        ):
            mock_settings.return_value.lan_username = "study"
            mock_settings.return_value.lan_password = "mypassword"  # pragma: allowlist secret
            mock_settings.return_value.ttyd_port = 7681
            result = runner.invoke(
                cli, ["web", "--lan", "--password", "mypassword"]
            )  # pragma: allowlist secret

        assert result.exit_code == 0
        assert mock_uvicorn._calls[0]["host"] == "0.0.0.0"

    def test_lan_without_password_generates_one(
        self, runner: CliRunner, mock_uvicorn, mock_web_app_module
    ) -> None:
        """web --lan without --password shows auto-generated credentials."""
        with (
            patch.dict(
                sys.modules,
                {"uvicorn": mock_uvicorn, "studyctl.web.app": mock_web_app_module},
            ),
            patch("studyctl.settings.load_settings") as mock_settings,
        ):
            mock_settings.return_value.lan_username = "study"
            mock_settings.return_value.lan_password = ""
            mock_settings.return_value.ttyd_port = 7681
            result = runner.invoke(cli, ["web", "--lan"])

        assert result.exit_code == 0
        assert "LAN credentials" in result.output
