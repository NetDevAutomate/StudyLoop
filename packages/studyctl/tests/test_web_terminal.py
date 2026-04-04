"""Playwright E2E tests for the terminal panel in session.html.

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


def _start_web_server(port: int = WEB_PORT) -> subprocess.Popen:
    """Start the studyctl web server in a subprocess."""
    import sys

    proc = subprocess.Popen(
        [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the server to be ready
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Web server failed to start on port {port}"
    raise RuntimeError(msg)


@pytest.fixture()
def web_server(_clean_ipc):
    """Start/stop the web server for each test."""
    proc = _start_web_server()
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Phase 1: Web UI tests (mocked state, no real ttyd)
# ---------------------------------------------------------------------------


class TestTerminalPanelUI:
    """Verify the terminal panel shows/hides based on session state."""

    def test_panel_hidden_when_no_ttyd_port(self, web_server, page):
        """Terminal panel should not be visible when ttyd_port is absent."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Python Decorators",
                "energy": 7,
                "mode": "active",
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")

        # Give Alpine.js time to init
        page.wait_for_timeout(1000)

        panel = page.locator(".terminal-panel")
        assert not panel.is_visible()

    def test_panel_visible_when_ttyd_port_present(self, web_server, page):
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

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        panel = page.locator(".terminal-panel")
        assert panel.is_visible()

        # Header shows "Agent Terminal"
        title = panel.locator(".terminal-title")
        assert title.text_content() == "Agent Terminal"

    def test_collapse_toggle_hides_iframe(self, web_server, page):
        """Clicking collapse button hides the iframe."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 7681,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        iframe = page.locator(".terminal-iframe")
        assert iframe.is_visible()

        # Click collapse button (first timer-btn in terminal-controls)
        collapse_btn = page.locator(".terminal-controls .timer-btn").first
        collapse_btn.click()
        page.wait_for_timeout(300)

        assert not iframe.is_visible()

        # Click again to re-show
        collapse_btn.click()
        page.wait_for_timeout(300)

        assert iframe.is_visible()

    def test_popout_button_opens_new_window(self, web_server, page, context):
        """Pop-out button opens ttyd URL in a new window."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 7681,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        # Pop-out is the second timer-btn in terminal-controls
        popout_btn = page.locator(".terminal-controls .timer-btn").nth(1)

        # Listen for new page (popup)
        with context.expect_page() as new_page_info:
            popout_btn.click()

        new_page = new_page_info.value
        assert "7681" in new_page.url

        # Wait for Alpine to process the state change
        page.wait_for_timeout(500)

        # After pop-out, iframe should be hidden, placeholder visible
        iframe = page.locator(".terminal-iframe")
        assert not iframe.is_visible()

        placeholder = page.locator(".terminal-placeholder")
        assert placeholder.is_visible()
        assert "separate window" in placeholder.text_content().lower()

    def test_iframe_src_uses_correct_port(self, web_server, page):
        """iframe src should use the ttyd_port from session state."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "ttyd_port": 9999,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        iframe = page.locator(".terminal-iframe")
        src = iframe.get_attribute("src")
        assert "9999" in src


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


class TestRealTtyd:
    """Tests with a real ttyd process — write to the terminal frame."""

    def test_ttyd_iframe_loads_terminal(self, web_server, ttyd_process, page):
        """The iframe loads a working ttyd terminal."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)

        # Verify the iframe is visible
        iframe_locator = page.locator(".terminal-iframe")
        assert iframe_locator.is_visible()

        # Access the iframe's content via frame_locator
        frame = page.frame_locator(".terminal-iframe")

        # ttyd renders a terminal element — wait for it
        xterm = frame.locator(".xterm")
        xterm.wait_for(timeout=10000)
        assert xterm.is_visible()

    def test_write_to_ttyd_frame(self, web_server, ttyd_process, page):
        """Type into the ttyd iframe and verify it reaches tmux."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Write Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)

        # Access the iframe content via frame_locator
        frame = page.frame_locator(".terminal-iframe")

        # Wait for xterm to be ready
        xterm = frame.locator(".xterm")
        xterm.wait_for(timeout=10000)

        # Click into the terminal to focus it
        xterm.click()
        page.wait_for_timeout(500)

        # Type a unique marker string
        marker = "PLAYWRIGHT_TTYD_TEST_42"
        xterm.type(f"echo {marker}")
        xterm.press("Enter")

        # Wait for the command to execute
        page.wait_for_timeout(2000)

        # Verify the marker appeared in the tmux pane
        pane_content = _capture_tmux_pane(ttyd_process["session"])
        assert marker in pane_content, f"Expected '{marker}' in tmux pane, got:\n{pane_content}"

    def test_popout_ttyd_window_is_interactive(self, web_server, ttyd_process, page, context):
        """Pop-out window loads a working, interactive ttyd terminal."""
        _write_state(
            {
                "study_session_id": "test-123",
                "topic": "ttyd Popout Test",
                "energy": 5,
                "ttyd_port": ttyd_process["port"],
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)

        # Click pop-out button
        popout_btn = page.locator(".terminal-controls .timer-btn").nth(1)
        with context.expect_page() as new_page_info:
            popout_btn.click()

        new_page = new_page_info.value
        new_page.wait_for_load_state("load")
        new_page.wait_for_timeout(2000)

        # The pop-out page IS ttyd directly — find the xterm element
        new_page.wait_for_selector(".xterm", timeout=10000)
        xterm = new_page.locator(".xterm")
        assert xterm.is_visible()

        # Type into it
        xterm.click()
        new_page.wait_for_timeout(500)

        marker = "POPOUT_TEST_99"
        xterm.type(f"echo {marker}")
        xterm.press("Enter")
        new_page.wait_for_timeout(2000)

        pane_content = _capture_tmux_pane(ttyd_process["session"])
        assert marker in pane_content
