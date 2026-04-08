"""Tests for the four fixes: pomodoro config, ttyd auth, ttyd lifecycle, terminal resilience.

Covers:
  1. Pomodoro config: Settings dataclass, API endpoint, web UI settings row
  2. ttyd auth: credentials passed via -c flag
  3. ttyd lifecycle: zombie detector kills stale ttyd
  4. Terminal panel: unavailable message when ttyd is down

Run:
    uv run pytest tests/test_fixes_pomodoro_auth_terminal.py -v
    uv run pytest tests/test_fixes_pomodoro_auth_terminal.py -v -k playwright  # E2E only
    uv run pytest tests/test_fixes_pomodoro_auth_terminal.py -v -k "not playwright"  # unit only
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyctl.settings import PomodoroConfig, load_settings
from studyctl.web.app import create_app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"

WEB_PORT = 18571  # Unique port to avoid conflicts


@pytest.fixture
def client() -> TestClient:
    app = create_app(study_dirs=[])
    return TestClient(app)


# ===================================================================
# 1. Pomodoro config — Settings + API
# ===================================================================


class TestPomodoroConfig:
    """PomodoroConfig dataclass and settings loading."""

    def test_default_values(self) -> None:
        pomo = PomodoroConfig()
        assert pomo.focus == 25
        assert pomo.short_break == 5
        assert pomo.long_break == 15
        assert pomo.cycles == 4

    def test_custom_values(self) -> None:
        pomo = PomodoroConfig(focus=30, short_break=10, long_break=20, cycles=3)
        assert pomo.focus == 30
        assert pomo.short_break == 10
        assert pomo.long_break == 20
        assert pomo.cycles == 3

    def test_load_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = tmp_path / "config.yaml"
        config.write_text(
            "pomodoro:\n  focus: 30\n  short_break: 10\n  long_break: 20\n  cycles: 3\n"
        )
        monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config)
        settings = load_settings()
        assert settings.pomodoro.focus == 30
        assert settings.pomodoro.short_break == 10
        assert settings.pomodoro.long_break == 20
        assert settings.pomodoro.cycles == 3

    def test_defaults_without_pomodoro_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "config.yaml"
        config.write_text("obsidian_base: ~/Obsidian\n")
        monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config)
        settings = load_settings()
        assert settings.pomodoro.focus == 25
        assert settings.pomodoro.short_break == 5


class TestPomodoroAPI:
    """GET /api/settings/pomodoro endpoint."""

    def test_returns_defaults(self, client: TestClient) -> None:
        resp = client.get("/api/settings/pomodoro")
        assert resp.status_code == 200
        data = resp.json()
        assert data["focus"] == 25
        assert data["short_break"] == 5
        assert data["long_break"] == 15
        assert data["cycles"] == 4

    def test_returns_config_values(self, client: TestClient) -> None:
        mock_settings = MagicMock()
        mock_settings.pomodoro = PomodoroConfig(focus=30, short_break=7, long_break=20, cycles=3)
        with patch("studyctl.settings.load_settings", return_value=mock_settings):
            resp = client.get("/api/settings/pomodoro")
        data = resp.json()
        assert data["focus"] == 30
        assert data["short_break"] == 7
        assert data["long_break"] == 20
        assert data["cycles"] == 3

    def test_returns_defaults_on_error(self, client: TestClient) -> None:
        with patch("studyctl.settings.load_settings", side_effect=Exception("boom")):
            resp = client.get("/api/settings/pomodoro")
        data = resp.json()
        assert data["focus"] == 25
        assert data["cycles"] == 4


# ===================================================================
# 2. ttyd auth — credential passthrough
# ===================================================================


class TestTtydAuth:
    """start_ttyd_background passes -c flag when credentials are provided."""

    def test_ttyd_cmd_includes_auth_flag(self) -> None:
        """Verify the command list includes -c username:password."""
        from studyctl.session.orchestrator import start_ttyd_background

        with (
            patch("shutil.which", return_value="/usr/bin/ttyd"),
            patch("subprocess.Popen") as mock_popen,
            patch("studyctl.session_state.write_session_state"),
        ):
            mock_popen.return_value = MagicMock(pid=12345)
            start_ttyd_background(
                "test-session",
                username="study",
                password="s3cret",  # pragma: allowlist secret
            )

        cmd = mock_popen.call_args[0][0]
        assert "-c" in cmd
        idx = cmd.index("-c")
        assert cmd[idx + 1] == "study:s3cret"
        assert "tmux" in cmd
        assert "test-session" in cmd

    def test_ttyd_cmd_no_auth_when_empty(self) -> None:
        """No -c flag when credentials are empty."""
        from studyctl.session.orchestrator import start_ttyd_background

        with (
            patch("shutil.which", return_value="/usr/bin/ttyd"),
            patch("subprocess.Popen") as mock_popen,
            patch("studyctl.session_state.write_session_state"),
        ):
            mock_popen.return_value = MagicMock(pid=12345)
            start_ttyd_background("test-session")

        cmd = mock_popen.call_args[0][0]
        assert "-c" not in cmd

    def test_ttyd_cmd_no_auth_when_password_only(self) -> None:
        """No -c flag when username is empty (both required)."""
        from studyctl.session.orchestrator import start_ttyd_background

        with (
            patch("shutil.which", return_value="/usr/bin/ttyd"),
            patch("subprocess.Popen") as mock_popen,
            patch("studyctl.session_state.write_session_state"),
        ):
            mock_popen.return_value = MagicMock(pid=12345)
            start_ttyd_background("test-session", password="secret")  # pragma: allowlist secret

        cmd = mock_popen.call_args[0][0]
        assert "-c" not in cmd


# ===================================================================
# 3. ttyd lifecycle — zombie detector kills stale ttyd
# ===================================================================


class TestTtydLifecycle:
    """_kill_stale_ttyd kills orphaned ttyd processes."""

    def test_kills_ttyd_by_pid(self) -> None:
        from studyctl.web.routes.session import _kill_stale_ttyd

        with (
            patch("subprocess.run") as mock_run,
            patch("os.kill") as mock_kill,
        ):
            mock_run.return_value = MagicMock(stdout="ttyd -W -i 127.0.0.1")
            _kill_stale_ttyd({"ttyd_pid": 99999})

        mock_kill.assert_called_once_with(99999, 15)

    def test_does_not_kill_non_ttyd_process(self) -> None:
        from studyctl.web.routes.session import _kill_stale_ttyd

        with (
            patch("subprocess.run") as mock_run,
            patch("os.kill") as mock_kill,
        ):
            mock_run.return_value = MagicMock(stdout="python some_other_thing")
            _kill_stale_ttyd({"ttyd_pid": 99999})

        mock_kill.assert_not_called()

    def test_no_op_without_pid(self) -> None:
        from studyctl.web.routes.session import _kill_stale_ttyd

        with patch("os.kill") as mock_kill:
            _kill_stale_ttyd({})

        mock_kill.assert_not_called()

    def test_zombie_detector_calls_kill_stale_ttyd(self) -> None:
        """_get_full_state kills ttyd when tmux session is dead."""
        from studyctl.web.routes.session import _get_full_state

        mock_state = {
            "tmux_session": "study-test-12345678",
            "ttyd_pid": 88888,
            "mode": "focus",
        }
        with (
            patch("studyctl.web.routes.session.read_session_state", return_value=mock_state),
            patch("studyctl.web.routes.session._is_tmux_session_alive", return_value=False),
            patch("studyctl.web.routes.session._kill_stale_ttyd") as mock_kill,
            patch("studyctl.web.routes.session.STATE_FILE", MagicMock(exists=lambda: False)),
            patch("studyctl.web.routes.session.TOPICS_FILE", MagicMock(exists=lambda: False)),
            patch("studyctl.web.routes.session.PARKING_FILE", MagicMock(exists=lambda: False)),
        ):
            result = _get_full_state()

        mock_kill.assert_called_once_with(mock_state)
        assert result == {"topics": [], "parking": []}


# ===================================================================
# 4. Playwright E2E — pomodoro UI + terminal resilience
# ===================================================================

# Guard Playwright tests separately
_pw = pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip("uvicorn")


@pytest.fixture()
def _clean_ipc():
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)
    yield
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)


def _write_state(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))


DEAD_TTYD_PORT = 19999  # Port where nothing listens — for resilience tests


def _start_web_server(port: int = WEB_PORT, ttyd_port: int = 0) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)]
    if ttyd_port:
        cmd.extend(["--ttyd-port", str(ttyd_port)])
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Web server failed to start on port {port}"
    raise RuntimeError(msg)


def _get_effective_credentials() -> tuple[str, str]:
    try:
        from studyctl.settings import load_settings as _ls

        s = _ls()
        return (s.lan_username or "study", s.lan_password or "")
    except Exception:
        return ("study", "")


_EFF_USER, _EFF_PASS = _get_effective_credentials()


@pytest.fixture()
def web_server(_clean_ipc):
    proc = _start_web_server()
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def web_page(web_server, browser):
    """Auth-enabled Playwright page."""
    ctx_args = {}
    if _EFF_PASS:
        ctx_args["http_credentials"] = {"username": _EFF_USER, "password": _EFF_PASS}
    context = browser.new_context(**ctx_args)
    yield context.new_page()
    context.close()


pytestmark_e2e = pytest.mark.e2e


class TestPomodoroWebUI:
    """Playwright tests for the configurable pomodoro timer."""

    pytestmark = [pytestmark_e2e]  # noqa: RUF012

    def test_pomodoro_settings_row_visible_when_stopped(self, web_page) -> None:
        """Settings row with Focus/Break/Long inputs is visible when timer is stopped."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(500)

        # Click the pomodoro header button to show the overlay (toggle, not start)
        header_btn = web_page.locator("header .toggle-btn[title*='Pomodoro']")
        header_btn.click()
        web_page.wait_for_timeout(500)

        # The pomodoro overlay should be visible
        pomo = web_page.locator(".pomodoro")
        assert pomo.is_visible()

        # Settings row should be visible (timer is not running)
        settings = pomo.locator(".pomo-settings")
        assert settings.is_visible()

        # Should have Focus, Break, Long inputs
        inputs = settings.locator(".pomo-input")
        assert inputs.count() == 3

        # A start button should be visible
        start_btn = pomo.locator(".pomo-start-btn")
        assert start_btn.is_visible()

    def test_pomodoro_settings_hidden_when_running(self, web_page) -> None:
        """Settings row hides when the pomodoro timer is running."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(500)

        # Show overlay
        header_btn = web_page.locator("header .toggle-btn[title*='Pomodoro']")
        header_btn.click()
        web_page.wait_for_timeout(500)

        pomo = web_page.locator(".pomodoro")

        # Click start to begin the timer
        start_btn = pomo.locator(".pomo-start-btn")
        start_btn.click()
        web_page.wait_for_timeout(500)

        settings = pomo.locator(".pomo-settings")
        # Timer is now running — settings should be hidden
        assert not settings.is_visible()

        # Stop it
        stop_btn = pomo.locator(".pomo-btn", has_text="\u00d7")
        stop_btn.click()
        web_page.wait_for_timeout(300)

    def test_pomodoro_display_reflects_custom_duration(self, web_page) -> None:
        """Changing focus duration updates the timer display."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(500)

        # Show pomodoro overlay
        header_btn = web_page.locator("header .toggle-btn[title*='Pomodoro']")
        header_btn.click()
        web_page.wait_for_timeout(500)

        pomo = web_page.locator(".pomodoro")
        # Change focus to 30 minutes
        focus_input = pomo.locator(".pomo-input").first
        focus_input.fill("30")
        focus_input.dispatch_event("change")
        web_page.wait_for_timeout(300)

        # Display should show 30:00 (not 25:00)
        display = pomo.locator(".pomo-time")
        assert display.text_content() == "30:00"

        # Start the timer via the start button
        start_btn = pomo.locator(".pomo-start-btn")
        start_btn.click()
        web_page.wait_for_timeout(1500)
        time_text = display.text_content()
        # Should be 29:5x (not 24:5x)
        assert time_text.startswith("29:")

        # Clean up — stop the timer
        stop_btn = pomo.locator(".pomo-btn", has_text="\u00d7")
        stop_btn.click()

    def test_pomodoro_settings_api_returns_data(self, web_page) -> None:
        """The /api/settings/pomodoro endpoint returns valid JSON."""
        resp = web_page.request.get(f"http://127.0.0.1:{WEB_PORT}/api/settings/pomodoro")
        assert resp.ok
        data = resp.json()
        assert "focus" in data
        assert "short_break" in data
        assert "long_break" in data
        assert "cycles" in data
        assert isinstance(data["focus"], int)


@pytest.fixture()
def web_server_dead_ttyd(_clean_ipc):
    """Web server pointed at a port where no ttyd is running."""
    proc = _start_web_server(ttyd_port=DEAD_TTYD_PORT)
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def web_page_dead_ttyd(web_server_dead_ttyd, browser):
    """Auth-enabled Playwright page for dead-ttyd tests."""
    ctx_args = {}
    if _EFF_PASS:
        ctx_args["http_credentials"] = {"username": _EFF_USER, "password": _EFF_PASS}
    context = browser.new_context(**ctx_args)
    yield context.new_page()
    context.close()


class TestTerminalResilience:
    """Playwright tests for terminal panel when ttyd is unavailable."""

    pytestmark = [pytestmark_e2e]  # noqa: RUF012

    def test_unavailable_message_when_ttyd_down(self, web_page_dead_ttyd) -> None:
        """Terminal panel shows 'session ended' when ttyd_port is set but ttyd is not running."""
        _write_state(
            {
                "study_session_id": "test-resilience",
                "topic": "Test Resilience",
                "energy": 5,
                "mode": "focus",
                "ttyd_port": DEAD_TTYD_PORT,
            }
        )

        web_page_dead_ttyd.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page_dead_ttyd.wait_for_load_state("load")

        # First verify the proxy returns 502 when ttyd is down
        resp = web_page_dead_ttyd.request.get(f"http://127.0.0.1:{WEB_PORT}/terminal/")
        assert resp.status == 502

        # Wait for Alpine health check to detect the failure.
        # The terminal panel should exist (available=true from ttyd_port in state)
        # and show an unavailable message (connected=false from failed probe).
        web_page_dead_ttyd.wait_for_timeout(3000)

        # Check Alpine state directly
        state = web_page_dead_ttyd.evaluate("""() => {
            const panels = document.querySelectorAll('.terminal-panel');
            const results = [];
            for (const p of panels) {
                const data = Alpine.$data(p);
                results.push({
                    available: data.available,
                    connected: data.connected,
                    unavailableMessage: data.unavailableMessage,
                    title: p.querySelector('.terminal-title')?.textContent || 'no title'
                });
            }
            return results;
        }""")

        # Find the study-session panel (Agent Terminal)
        agent_panel = next((s for s in state if "Agent" in s.get("title", "")), None)
        assert agent_panel is not None, f"Could not find Agent Terminal panel. State: {state}"
        assert agent_panel["available"] is True, f"Panel not available: {agent_panel}"
        assert agent_panel["connected"] is False, f"Panel should not be connected: {agent_panel}"
        assert agent_panel["unavailableMessage"], f"No unavailable message: {agent_panel}"

        # Verify the unavailable div is visible in the DOM
        panel = web_page_dead_ttyd.locator(".terminal-panel", has_text="Agent Terminal")
        unavailable = panel.locator(".terminal-unavailable")
        assert unavailable.is_visible(), (
            f"Unavailable div not visible. Panel visible={panel.is_visible()}, "
            f"Alpine state: {agent_panel}"
        )

        # The iframe should be hidden (connected=false, x-show hides it)
        iframe = panel.locator(".terminal-iframe")
        assert not iframe.is_visible()

    def test_no_unavailable_when_no_ttyd_port(self, web_page_dead_ttyd) -> None:
        """No unavailable message when ttyd_port is not in state."""
        _write_state(
            {
                "study_session_id": "test-no-ttyd",
                "topic": "No TTYD",
                "energy": 5,
            }
        )

        web_page_dead_ttyd.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page_dead_ttyd.wait_for_load_state("load")
        web_page_dead_ttyd.wait_for_timeout(1000)

        # Panel should not be visible at all
        panel = web_page_dead_ttyd.locator(".terminal-panel", has_text="Agent Terminal")
        assert not panel.is_visible()
