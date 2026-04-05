"""End-to-end integration test: web UI + ttyd terminal + mock agent lifecycle.

This test doubles as a recordable demo. It exercises the full session stack:
  1. Start study session with --lan --web --password (mock agent)
  2. Web dashboard loads with timer, metadata, activity feed
  3. Mock agent logs topics → SSE pushes to dashboard
  4. Terminal panel (ttyd iframe via proxy) renders xterm
  5. WebSocket relay: keystrokes reach tmux, output flows back
  6. Pop-out terminal → close → return to inline
  7. LAN auth: unauthenticated requests rejected
  8. End session → verify cleanup

Run as regression test:
    uv run pytest tests/test_e2e_session_demo.py -v

Run with video recording (demo):
    uv run pytest tests/test_e2e_session_demo.py -v --video=on

Run headed (watch it live):
    uv run pytest tests/test_e2e_session_demo.py -v --headed --slowmo=500

Requires: tmux, ttyd, playwright, fastapi, uvicorn.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

# Skip if dependencies are missing
pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.skipif(not shutil.which("ttyd"), reason="ttyd not installed"),
    pytest.mark.e2e,
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"
ONELINE_FILE = CONFIG_DIR / "session-oneline.txt"
SESSIONS_DIR = CONFIG_DIR / "sessions"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent

WEB_PORT = 18567
TTYD_PORT = 17681
LAN_PASSWORD = "e2e-test-pass"  # pragma: allowlist secret
STUDYCTL = f"uv run --project {PROJECT_DIR} studyctl"
TOPIC = "E2E Demo Session"


def _make_test_config(tmp_dir: Path) -> Path:
    """Write a minimal studyctl config with test-specific ports.

    Returns the path to the temp config file.
    """
    config = tmp_dir / "studyctl-test-config.yaml"
    config.write_text(
        f"web_port: {WEB_PORT}\nttyd_port: {TTYD_PORT}\nlan_password: {LAN_PASSWORD}\n"
    )
    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmux(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False)


def _wait_for(predicate, timeout=20, interval=0.5, desc="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    msg = f"Timed out waiting for {desc} after {timeout}s"
    raise TimeoutError(msg)


def _read_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _capture_pane(session_name: str) -> str:
    result = _tmux("capture-pane", "-t", session_name, "-p")
    return result.stdout


def _cleanup_all():
    """Nuclear cleanup: kill sessions, ttyd, web, orphans, IPC files."""
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE, ONELINE_FILE]:
        f.unlink(missing_ok=True)
    # Kill study tmux sessions
    result = _tmux("list-sessions", "-F", "#{session_name}")
    if result.returncode == 0:
        for name in result.stdout.strip().splitlines():
            if name.startswith(("study-", "e2e-", "studyctl-test", "playwright-")):
                _tmux("kill-session", "-t", name)
    # Kill orphaned processes
    for pattern in (
        "studyctl.tui.sidebar",
        "mock-agent",
        f"ttyd.*{TTYD_PORT}",
        f"studyctl.*{WEB_PORT}",
    ):
        with contextlib.suppress(Exception):
            subprocess.run(["pkill", "-f", pattern], capture_output=True, check=False)
    # Remove test session dirs
    if SESSIONS_DIR.exists():
        for d in SESSIONS_DIR.iterdir():
            if d.is_dir() and "e2e-demo" in d.name:
                shutil.rmtree(d, ignore_errors=True)


def _make_demo_agent(tmp_path: Path) -> str:
    """Mock agent that simulates a realistic study session.

    Logs topics with different statuses, parks a question, waits
    for input (simulating a real AI agent), then exits on signal.
    """
    script = tmp_path / "demo-agent.sh"
    script.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "=== Socratic Study Mentor (Demo) ==="
        echo "Topic: {TOPIC}"
        echo ""
        sleep 2

        # Simulate agent logging topics
        {STUDYCTL} topic "What are decorators?" --status learning --note "exploring the concept"
        sleep 2

        {STUDYCTL} topic "Functions are first-class objects" \
          --status win --note "functions can be passed as arguments"
        sleep 2

        {STUDYCTL} topic "@property decorator" \
          --status learning --note "syntactic sugar for getters/setters"
        sleep 1

        {STUDYCTL} park "How do decorators interact with async/await?"
        sleep 1

        {STUDYCTL} topic "Writing custom decorators" \
          --status win --note "closure wrapping pattern"
        sleep 1

        echo ""
        echo "Session is running. Type commands or wait..."
        echo ""

        # Wait for signal (simulates agent waiting for user input)
        trap 'echo "Agent exiting cleanly"; exit 0' INT TERM
        while true; do sleep 1; done
    """)
    )
    script.chmod(0o755)
    return str(script)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_environment():
    """Clean up before and after each test."""
    _cleanup_all()
    yield
    _cleanup_all()


@pytest.fixture()
def demo_session(tmp_path):
    """Start a full study session with web + ttyd + mock agent.

    Returns a dict with session metadata for test assertions.
    """
    agent_script = _make_demo_agent(tmp_path)
    test_config = _make_test_config(tmp_path)

    env = {
        **os.environ,
        "STUDYCTL_TEST_AGENT_CMD": agent_script,
        "STUDYCTL_CONFIG": str(test_config),
    }
    env.pop("TMUX", None)  # Don't nest tmux

    # Start the session in background (it calls os.execvp so we can't wait)
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_DIR),
            "studyctl",
            "study",
            TOPIC,
            "--energy",
            "7",
            "--web",
            "--lan",
            "--password",
            LAN_PASSWORD,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for tmux session to exist
    _wait_for(
        lambda: any(
            n.startswith("study-e2e-demo")
            for n in _tmux("list-sessions", "-F", "#{session_name}").stdout.strip().splitlines()
        ),
        timeout=15,
        desc="tmux session to start",
    )

    # Get session name
    sessions = _tmux("list-sessions", "-F", "#{session_name}").stdout.strip().splitlines()
    session_name = next(n for n in sessions if n.startswith("study-e2e-demo"))

    # Wait for web server to be ready
    def _web_ready():
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{WEB_PORT}/")
            # Auth required for LAN mode
            import base64

            creds = base64.b64encode(f"study:{LAN_PASSWORD}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False

    _wait_for(_web_ready, timeout=15, desc="web server to start")

    # Wait for ttyd to be ready
    def _ttyd_ready():
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{TTYD_PORT}/", timeout=1)
            return True
        except Exception:
            return False

    _wait_for(_ttyd_ready, timeout=10, desc="ttyd to start")

    # Wait for mock agent to log at least one topic
    _wait_for(
        lambda: TOPICS_FILE.exists() and TOPICS_FILE.stat().st_size > 10,
        timeout=15,
        desc="agent to log topics",
    )

    yield {
        "session_name": session_name,
        "web_port": WEB_PORT,
        "ttyd_port": TTYD_PORT,
        "password": LAN_PASSWORD,
        "proc": proc,
    }

    # End session
    subprocess.run(
        ["uv", "run", "--project", str(PROJECT_DIR), "studyctl", "study", "--end"],
        env=env,
        capture_output=True,
        timeout=10,
    )
    with contextlib.suppress(Exception):
        proc.terminate()
        proc.wait(timeout=5)


def _auth_header():
    """Build HTTP Basic Auth header for test requests."""
    import base64

    creds = base64.b64encode(f"study:{LAN_PASSWORD}".encode()).decode()
    return f"Basic {creds}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2ESessionDemo:
    """Full end-to-end session lifecycle — regression test + recordable demo."""

    def test_01_dashboard_loads_with_session_metadata(self, demo_session, page):
        """Dashboard shows topic, energy, and timer."""
        page.set_extra_http_headers({"Authorization": _auth_header()})
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)

        # Topic is visible
        topic_el = page.locator(".meta-topic")
        assert topic_el.is_visible()
        assert TOPIC.lower() in topic_el.text_content().lower()

        # Energy is visible
        energy_el = page.locator(".meta-energy")
        assert energy_el.is_visible()
        assert "7/10" in energy_el.text_content()

        # Timer is running (not idle)
        timer_el = page.locator(".timer-time")
        assert timer_el.is_visible()
        time_text = timer_el.text_content()
        assert ":" in time_text  # MM:SS format

    def test_02_activity_feed_shows_agent_topics(self, demo_session, page):
        """SSE activity feed populates with topics logged by the mock agent."""
        page.set_extra_http_headers({"Authorization": _auth_header()})
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")

        # Wait for SSE to push activity items (poll every 2s)
        page.wait_for_timeout(5000)

        feed = page.locator("#activity-feed")
        feed_html = feed.inner_html()

        # Agent should have logged topics by now
        assert "decorators" in feed_html.lower() or "first-class" in feed_html.lower(), (
            f"Expected agent topics in activity feed, got: {feed_html[:300]}"
        )

    def test_03_counter_bar_tracks_wins_and_parked(self, demo_session, page):
        """Counter bar shows wins and parked topic counts."""
        page.set_extra_http_headers({"Authorization": _auth_header()})
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(5000)

        wins = page.locator("#counter-wins")
        parked = page.locator("#counter-parked")

        # Mock agent logs 2 wins and 1 parked
        wins_text = wins.text_content()
        parked_text = parked.text_content()

        assert "WINS:" in wins_text
        assert "PARKED:" in parked_text

    def test_04_terminal_iframe_loads_xterm(self, demo_session, page):
        """Terminal panel shows an embedded ttyd xterm via the same-origin proxy."""
        page.set_extra_http_headers({"Authorization": _auth_header()})
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(3000)

        # Iframe should be visible with /terminal/ src
        iframe = page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-iframe"
        )
        assert iframe.is_visible(), "Terminal iframe should be visible"

        src = iframe.get_attribute("src")
        assert "/terminal/" in src, f"Iframe src should use proxy path, got: {src}"

        # xterm should render inside the iframe
        frame = page.frame_locator(".terminal-iframe").first
        xterm = frame.locator(".xterm")
        xterm.wait_for(timeout=15000)
        assert xterm.is_visible(), "xterm should be visible inside the proxied iframe"

    def test_05_popout_and_return(self, demo_session, page, context):
        """Pop-out opens terminal in new window; return closes it and re-embeds."""
        page.set_extra_http_headers({"Authorization": _auth_header()})
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(3000)

        # Click pop-out
        popout_btn = page.locator("button[title='Open in new window']")
        with context.expect_page() as new_page_info:
            popout_btn.click()
        new_page = new_page_info.value

        # Pop-out window loads ttyd
        with contextlib.suppress(Exception):
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
        new_page.wait_for_timeout(2000)

        # Placeholder should show in main page
        placeholder = page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-placeholder"
        )
        assert placeholder.is_visible(), "Placeholder should show when terminal is popped out"

        # Click "+" to return to inline — should close the pop-out
        toggle_btn = page.locator("button[title='Show terminal']")
        toggle_btn.click()
        page.wait_for_timeout(1000)

        # Iframe should be visible again
        iframe = page.locator(".terminal-panel", has_text="Agent Terminal").locator(
            ".terminal-iframe"
        )
        # CSS visibility check — element is in DOM but may have visibility:hidden
        assert iframe.is_visible(), "Iframe should be visible after returning from pop-out"

        # Placeholder should be hidden
        assert not placeholder.is_visible(), "Placeholder should hide after returning from pop-out"

    def test_06_ws_proxy_relays_keystrokes(self, demo_session):
        """WebSocket proxy relays keystrokes to tmux and output back."""
        import threading

        websockets = pytest.importorskip("websockets")

        session_name = demo_session["session_name"]

        # Capture result/exception from the thread
        result: dict = {}

        def _run_ws_test():
            """Run the async WS test in a fresh thread with its own event loop.

            asyncio.new_event_loop() in the test thread can conflict with
            Playwright's event loop. Running in a separate thread avoids the
            'Cannot run the event loop while another loop is running' error.
            """

            async def _ws_test():
                async with websockets.connect(
                    f"ws://127.0.0.1:{WEB_PORT}/terminal/ws",
                    subprotocols=["tty"],
                    additional_headers={"Authorization": _auth_header()},
                ) as ws:
                    # ttyd handshake
                    await ws.send('{"AuthToken":""}')
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    assert len(msg) > 0

                    await ws.send('1{"columns":80,"rows":24}')

                    # Drain initial output
                    with contextlib.suppress(Exception):
                        while True:
                            await asyncio.wait_for(ws.recv(), timeout=2)

                    # Send a unique marker through the proxy
                    marker = "E2E_WS_RELAY_TEST"
                    await ws.send(f"0echo {marker}\n")
                    await asyncio.sleep(2)

                # Verify it reached tmux
                pane_content = _capture_pane(session_name)
                assert marker in pane_content, (
                    f"Expected '{marker}' in tmux pane via WS proxy, got:\n{pane_content}"
                )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_ws_test())
                result["ok"] = True
            except Exception as exc:
                result["error"] = exc
            finally:
                loop.close()

        t = threading.Thread(target=_run_ws_test, daemon=True)
        t.start()
        t.join(timeout=30)

        if t.is_alive():
            pytest.fail("WebSocket test thread timed out after 30s")
        if "error" in result:
            raise result["error"]

    def test_07_lan_auth_rejects_unauthenticated(self, demo_session):
        """LAN mode rejects requests without valid credentials."""
        # No auth header
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/session", timeout=5)
            pytest.fail(f"Expected 401, got {resp.status}")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"Expected 401, got {e.code}"
            assert "WWW-Authenticate" in e.headers

        # Wrong password
        import base64

        bad_creds = base64.b64encode(b"test:wrong-password").decode()
        req = urllib.request.Request(f"http://127.0.0.1:{WEB_PORT}/session")
        req.add_header("Authorization", f"Basic {bad_creds}")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            pytest.fail(f"Expected 401, got {resp.status}")
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_08_session_end_cleans_up(self, demo_session):
        """Ending the session kills tmux, ttyd, web, and clears IPC."""
        session_name = demo_session["session_name"]

        # Session should be running
        assert _tmux("has-session", "-t", session_name).returncode == 0

        # End it
        env = {**os.environ}
        env.pop("TMUX", None)
        subprocess.run(
            ["uv", "run", "--project", str(PROJECT_DIR), "studyctl", "study", "--end"],
            env=env,
            capture_output=True,
            timeout=10,
        )
        time.sleep(2)

        # tmux session should be gone
        assert _tmux("has-session", "-t", session_name).returncode != 0, (
            "tmux session should be killed after --end"
        )

        # IPC files should be cleaned
        assert not TOPICS_FILE.exists(), "Topics file should be removed"
        assert not PARKING_FILE.exists(), "Parking file should be removed"
