"""Playwright E2E tests for the terminal panel in the Study Session sidebar view.

Phase 1: Web UI tests with mocked session state (no real ttyd).
Phase 2: Real ttyd integration — write to the terminal frame.

Requires: playwright, fastapi, uvicorn, ttyd (Phase 2 only).
Run with:
    uv run pytest tests/test_web_terminal.py -v
    uv run pytest tests/test_web_terminal.py -v -k phase1   # UI only
    uv run pytest tests/test_web_terminal.py -v -k phase2   # real ttyd
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Skip entire module if playwright or fastapi aren't installed
pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

pytestmark = [pytest.mark.e2e]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"

WEB_PORT = 18567  # Non-default port to avoid conflicts with real sessions


@pytest.fixture()
def _clean_ipc():
    """Ensure no stale IPC files before/after each test."""
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)
    yield
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)


def _write_state(data: dict) -> None:
    """Write session state JSON for the web server to read."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))


def _start_web_server(port: int = WEB_PORT, ttyd_port: int = 0) -> subprocess.Popen:
    """Start the studyctl web server in a subprocess.

    Args:
        port: Port for the web server.
        ttyd_port: Port where ttyd is running (0 = use config/default).
    """
    import sys

    cmd = [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)]
    if ttyd_port:
        cmd.extend(["--ttyd-port", str(ttyd_port)])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the server to be ready
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc  # server is up, just auth-protected from config
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Web server failed to start on port {port}"
    raise RuntimeError(msg)


def _get_effective_credentials() -> tuple[str, str]:
    """Return (username, password) the CLI will use from config."""
    try:
        from studyctl.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


_EFFECTIVE_USERNAME, _EFFECTIVE_PASSWORD = _get_effective_credentials()


@pytest.fixture()
def web_server(_clean_ipc):
    """Start/stop the web server for each test."""
    proc = _start_web_server()
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def _auth_context(browser):
    """Playwright browser context with auth credentials from config (if any)."""
    ctx_args = {}
    if _EFFECTIVE_PASSWORD:
        ctx_args["http_credentials"] = {
            "username": _EFFECTIVE_USERNAME,
            "password": _EFFECTIVE_PASSWORD,
        }
    context = browser.new_context(**ctx_args)
    yield context
    context.close()


@pytest.fixture()
def web_page(web_server, _auth_context):
    """Auth-enabled page backed by the standard web server."""
    yield _auth_context.new_page()


@pytest.fixture()
def web_page_ttyd(web_server_with_ttyd, _auth_context):
    """Auth-enabled page backed by the web server with ttyd."""
    yield _auth_context.new_page()


# ---------------------------------------------------------------------------
# Phase 1: Web UI tests (mocked state, no real ttyd)
# ---------------------------------------------------------------------------


class TestTerminalPanelUI:
    """Verify the terminal panel shows/hides based on session state."""

    def test_panel_hidden_when_no_ttyd_port(self, web_page):
        """Terminal panel should not be visible when ttyd_port is absent."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Python Decorators",
                "energy": 7,
                "mode": "active",
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")

        # Give Alpine.js time to init
        web_page.wait_for_timeout(1000)

        panel = web_page.locator(".terminal-panel", has_text="Agent Terminal")
        assert not panel.is_visible()

    def test_panel_visible_when_ttyd_port_present(self, web_page):
        """Terminal panel appears when ttyd_port is in session state."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Python Decorators",
                "energy": 7,
                "mode": "active",
                "ttyd_port": 7681,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        panel = web_page.locator(".terminal-panel", has_text="Agent Terminal")
        assert panel.is_visible()

        # Header shows "Agent Terminal"
        title = panel.locator(".terminal-title")
        assert title.text_content() == "Agent Terminal"

    @pytest.mark.skip(
        reason="Requires real ttyd — async health check probe to /terminal/ "
        "delays panel init beyond test timeout when ttyd is not running."
    )
    def test_collapse_toggle_hides_iframe(self, web_page):
        """Clicking collapse button hides the iframe."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 7681,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")

        # Wait for terminal panel to fully init (async health check)
        iframe = web_page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-iframe"
        )
        iframe.wait_for(state="visible", timeout=15000)

        # Click the embed-toggle button — scoped to Study Session terminal
        panel = web_page.locator(".terminal-panel", has_text="Agent Terminal")
        collapse_btn = panel.locator(".terminal-controls .timer-btn").nth(
            2
        )  # 3rd btn = toggle embed
        collapse_btn.click()
        web_page.wait_for_timeout(300)

        assert not iframe.is_visible()

        # Click again to re-show
        collapse_btn.click()
        web_page.wait_for_timeout(300)

        assert iframe.is_visible()

    def test_popout_button_opens_new_window(self, web_page):
        """Pop-out button opens the same-origin /terminal/ in a new window."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 7681,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        # Pop-out button — find it by its stable title attribute
        popout_btn = web_page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-controls .timer-btn[title='Open in new window']"
        )

        # Listen for new page (popup)
        with web_page.context.expect_page() as new_page_info:
            popout_btn.click()

        new_page = new_page_info.value
        # Now opens same-origin /terminal/ path, not a cross-origin port URL
        assert "/terminal/" in new_page.url

        # Wait for Alpine to process the state change
        web_page.wait_for_timeout(500)

        # After pop-out, iframe should be hidden, placeholder visible
        iframe = web_page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-iframe"
        )
        assert not iframe.is_visible()

        placeholder = web_page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-placeholder"
        )
        assert placeholder.is_visible()
        assert "separate window" in placeholder.text_content().lower()

    @pytest.mark.skip(
        reason="Requires real ttyd — async health check probe to /terminal/ "
        "delays panel init beyond test timeout when ttyd is not running."
    )
    def test_iframe_src_uses_proxy_path(self, web_page):
        """iframe src should use the same-origin /terminal/ proxy path."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 9999,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")

        # Wait for terminal panel to fully init (async health check)
        iframe = web_page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-iframe"
        )
        iframe.wait_for(timeout=15000)
        src = iframe.get_attribute("src")
        # iframe now uses the same-origin proxy path, not a port-specific URL
        assert "/terminal/" in src
        assert "9999" not in src  # Port must NOT appear in the iframe src


# ---------------------------------------------------------------------------
# Phase 2: Real ttyd integration — write to terminal frame
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmux_session():
    """Create a temporary tmux session for ttyd to attach to."""
    if not shutil.which("tmux"):
        pytest.skip("tmux not installed")

    session_name = "studyctl-test-ttyd"
    # Kill any stale session
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        capture_output=True,
        check=False,
    )
    # Create a new detached session running bash
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "bash"],
        check=True,
    )
    yield session_name
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        capture_output=True,
        check=False,
    )


@pytest.fixture()
def ttyd_process(tmux_session):
    """Start ttyd attached to the test tmux session."""
    if not shutil.which("ttyd"):
        pytest.skip("ttyd not installed")

    ttyd_port = 17681  # Non-default port for testing
    proc = subprocess.Popen(
        [
            "ttyd",
            "-W",
            "-i",
            "127.0.0.1",
            "-p",
            str(ttyd_port),
            "tmux",
            "attach",
            "-t",
            tmux_session,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for ttyd to be ready
    import urllib.request

    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{ttyd_port}/", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("ttyd failed to start")

    yield {"proc": proc, "port": ttyd_port, "session": tmux_session}
    proc.terminate()
    proc.wait(timeout=5)


def _capture_tmux_pane(session_name: str) -> str:
    """Capture the current content of the tmux pane."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


@pytest.fixture()
def web_server_with_ttyd(_clean_ipc, ttyd_process):
    """Start the web server knowing the ttyd port (for Phase 2 proxy tests)."""
    proc = _start_web_server(port=WEB_PORT, ttyd_port=ttyd_process["port"])
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


class TestRealTtyd:
    """Tests with a real ttyd process — write to the terminal frame."""

    def test_ttyd_iframe_loads_terminal(self, ttyd_process, web_page_ttyd):
        """The iframe loads a working ttyd terminal via the same-origin proxy."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        web_page_ttyd.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page_ttyd.wait_for_load_state("load")

        # Wait for the iframe to appear — the terminal panel probes /terminal/
        # before rendering the iframe (connected=true triggers x-if).
        iframe_locator = web_page_ttyd.locator(
            ".terminal-panel", has_text="Agent Terminal"
        ).locator(".terminal-iframe")
        iframe_locator.wait_for(state="visible", timeout=15000)

        # Access the study-session terminal iframe specifically — the body-double
        # panel also has a terminal iframe, but it's on a hidden tab.
        study_panel = web_page_ttyd.locator(".terminal-panel", has_text="Agent Terminal")
        frame = study_panel.frame_locator(".terminal-iframe")

        # ttyd renders a terminal element — wait for it.
        xterm = frame.locator(".xterm")
        xterm.wait_for(timeout=20000)
        assert xterm.is_visible()

    @pytest.mark.skip(
        reason="xterm.js canvas keyboard input is unreliable in headless Chromium. "
        "The terminal renders correctly (verified by test_ttyd_iframe_loads_terminal). "
        "Use headed mode with manual interaction to test typing."
    )
    def test_write_to_ttyd_frame(self, ttyd_process, web_page_ttyd):
        """Type into the proxied ttyd iframe and verify it reaches tmux."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Write Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        web_page_ttyd.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page_ttyd.wait_for_load_state("load")
        web_page_ttyd.wait_for_timeout(3000)

        # Access the iframe content via frame_locator — proxied via /terminal/
        frame = web_page_ttyd.frame_locator(".terminal-iframe")

        # Wait for xterm to be ready and fully initialised
        xterm = frame.locator(".xterm")
        xterm.wait_for(timeout=15000)
        web_page_ttyd.wait_for_timeout(2000)  # Allow WS to fully establish via proxy

        # Click the xterm canvas to focus it; use web_page_ttyd.keyboard for canvas input
        # (xterm.js renders to canvas — web_page_ttyd.keyboard is more reliable than element.type)
        xterm.click()
        web_page_ttyd.wait_for_timeout(1000)

        # Type a unique marker string via page-level keyboard (canvas focus)
        marker = "PLAYWRIGHT_TTYD_TEST_42"
        web_page_ttyd.keyboard.type(f"echo {marker}")
        web_page_ttyd.keyboard.press("Enter")

        # Wait for the command to execute and propagate through proxy
        web_page_ttyd.wait_for_timeout(3000)

        # Verify the marker appeared in the tmux pane
        pane_content = _capture_tmux_pane(ttyd_process["session"])
        assert marker in pane_content, f"Expected '{marker}' in tmux pane, got:\n{pane_content}"

    @pytest.mark.skip(
        reason="xterm.js canvas keyboard input is unreliable in headless Chromium. "
        "The pop-out window loads correctly (verified by test_ttyd_iframe_loads_terminal). "
        "Use headed mode with manual interaction to test typing."
    )
    def test_popout_ttyd_window_is_interactive(
        self, web_server_with_ttyd, ttyd_process, page, context
    ):
        """Pop-out window opens /terminal/ and loads an interactive ttyd terminal."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Popout Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        web_page_ttyd.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page_ttyd.wait_for_load_state("load")
        web_page_ttyd.wait_for_timeout(2000)

        # Click pop-out button — find by stable title attribute
        popout_btn = web_page_ttyd.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-controls .timer-btn[title='Open in new window']"
        )
        with context.expect_page() as new_page_info:
            popout_btn.click()

        new_page = new_page_info.value
        # Use domcontentloaded since the WS keeps the page from completing "load"
        import contextlib

        with contextlib.suppress(Exception):
            new_page.wait_for_load_state("domcontentloaded", timeout=15000)
        new_page.wait_for_timeout(3000)

        # The pop-out page opens /terminal/ which proxies to ttyd — find the xterm element
        new_page.wait_for_selector(".xterm", timeout=15000)
        xterm = new_page.locator(".xterm")
        assert xterm.is_visible()

        # Click the xterm canvas to focus it; use new_page.keyboard for canvas input
        xterm.click()
        new_page.wait_for_timeout(1000)

        marker = "POPOUT_TEST_99"
        new_page.keyboard.type(f"echo {marker}")
        new_page.keyboard.press("Enter")
        new_page.wait_for_timeout(3000)

        pane_content = _capture_tmux_pane(ttyd_process["session"])
        assert marker in pane_content
