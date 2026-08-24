"""Opt-in Playwright rendering gate for the real coding-agent TUIs.

The deterministic matrix in ``test_web_agent_matrix.py`` is the required CI
gate: it proves StudyLoop's adapter, PTY, WebSocket, resize, refresh and input
contracts without credentials. This module adds the other half of the truth:
the locally installed vendor TUI must actually paint and remain interactive in
the stock xterm surface.

It is deliberately excluded from normal/e2e runs because it starts real agents
and may use provider quota. Run it explicitly with ``-m live_harness`` for a
permissive local smoke check, or use ``just test-live-harnesses`` for the
fail-closed five-harness release gate. StudyLoop state is hermetic; HOME remains
real only so each CLI can use its existing authentication.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from test_web_agent_matrix import (  # noqa: E402
    _empty_backlog,
    _end_any_active_session,
    _session_state,
    _terminal_snapshot,
    _wait_for_terminal_geometry,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.live_harness, pytest.mark.timeout(180)]

_BINARY = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "kiro": "kiro-cli",
    "opencode": "opencode",
}
LIVE_HARNESS_AGENTS = ["claude", "codex", "gemini", "kiro", "opencode"]
_BASE_PORT = 18730
_STUDY_CONSOLE = '.session-terminal-area.agent-console[x-data="liveAgentConsole()"]'
_AUTH_GATE_TEXT = (
    "approve in your browser to finish signing in",
    "authentication required",
    "not authenticated",
    "please log in",
)
_STRICT_GATE_ENV = "STUDYLOOP_STRICT_LIVE_HARNESSES"


def _unavailable_harness(agent: str, reason: str) -> None:
    """Skip local smoke runs, but fail closed for an explicit release gate."""
    message = f"{agent}: {reason}"
    if os.environ.get(_STRICT_GATE_ENV) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


def _start_live_server(root: Path, agent: str, port: int) -> subprocess.Popen:
    """Start release-mode StudyLoop with real harness auth but isolated state."""
    state_dir = root / "state"
    session_dir = root / "session-ipc"
    plans_dir = root / "plans"
    vault = root / "vault"
    for directory in (state_dir, session_dir, plans_dir, vault):
        directory.mkdir(parents=True, exist_ok=True)

    db_path = root / "sessions.db"
    config_path = root / "config.yaml"
    config_path.write_text(
        f"session_db: {db_path}\ncontent:\n  base_path: {vault}\n  study_paths:\n    - {vault}\n",
        encoding="utf-8",
    )
    from agent_session_tools.export_sessions import init_db

    init_db(str(db_path)).close()

    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(config_path),
        "STUDYLOOP_DB": str(db_path),
        "STUDYLOOP_STATE_DIR": str(state_dir),
        "STUDYLOOP_SESSION_DIR": str(session_dir),
        "STUDYLOOP_PLANS_DIR": str(plans_dir),
        "STUDYLOOP_SKIP_LEGACY_MIGRATION": "1",
    }
    # The live lane must never silently become the deterministic shim lane.
    env.pop("STUDYLOOP_TEST_AGENT_CMD", None)
    if agent != "kiro":
        env.pop("STUDYLOOP_KIRO_AGENTS_DIR", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).close()
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session/state", timeout=5).close()
            return proc
        except urllib.error.HTTPError:
            time.sleep(0.25)
        except Exception:
            time.sleep(0.25)
    proc.kill()
    proc.wait(timeout=5)
    raise RuntimeError(f"live {agent} web server failed to start on port {port}")


@pytest.fixture(params=LIVE_HARNESS_AGENTS)
def live_harness(request, tmp_path_factory: pytest.TempPathFactory):
    agent = request.param
    binary = _BINARY[agent]
    if not shutil.which(binary):
        _unavailable_harness(agent, f"{binary} is not installed")
    port = _BASE_PORT + LIVE_HARNESS_AGENTS.index(agent)
    root = tmp_path_factory.mktemp(f"live-web-{agent}").resolve()
    proc = _start_live_server(root, agent, port)
    try:
        yield agent, port, root
    finally:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/session/end", method="POST")
            urllib.request.urlopen(req, timeout=10).close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _wait_for_real_tui_text(page: Page) -> str:
    """Wait for content beyond StudyLoop's own connecting placeholder."""
    page.wait_for_function(
        """(selector) => {
          const root = document.querySelector(selector);
          if (!root || !window.Alpine || !window.Alpine.$data) return false;
          const term = window.Alpine.$data(root)._term;
          if (!term || !term.buffer) return false;
          const buffer = term.buffer.active;
          let text = '';
          for (let index = 0; index < buffer.length; index += 1) {
            const line = buffer.getLine(index);
            if (line) text += line.translateToString(true) + '\\n';
          }
          return text.replace('Connecting to agent...', '').trim().length >= 3;
        }""",
        arg=_STUDY_CONSOLE,
        timeout=45_000,
    )
    return _terminal_snapshot(page)["text"]


def test_real_harness_tui_renders_resizes_and_reattaches(browser: Browser, live_harness) -> None:
    """Real TUI smoke: paint, shrink, refresh, type, and grow."""
    agent, port, root = live_harness
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.route("**/api/backlog", _empty_backlog)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_function("() => !!window.Alpine", timeout=15_000)
        page.get_by_role("button", name="Study Session", exact=True).click()
        page.locator("#topic-input").wait_for(state="visible", timeout=15_000)
        page.locator("#topic-input").fill(f"Live rendering {agent}")
        page.wait_for_function(
            """(agent) => {
              const select = document.querySelector('#agent-select');
              return select && [...select.options].some(
                (option) => option.value === agent && !option.disabled
              );
            }""",
            arg=agent,
            timeout=45_000,
        )
        page.select_option("#agent-select", value=agent)
        assert page.locator("#transport-select").input_value() == "pty"
        page.locator(".study-start-picker .start-session-btn").click()
        page.wait_for_function(
            """(selector) => {
              const root = document.querySelector(selector);
              if (!root || !window.Alpine || !window.Alpine.$data) return false;
              const data = window.Alpine.$data(root);
              return data && data.connected === true && data.terminalMode === 'xterm';
            }""",
            arg=_STUDY_CONSOLE,
            timeout=45_000,
        )
        _wait_for_terminal_geometry(page, timeout=30_000)
        initial_text = _wait_for_real_tui_text(page)
        wide = _terminal_snapshot(page)
        assert wide["width"] > 100 and wide["height"] > 50

        page.set_viewport_size({"width": 820, "height": 560})
        page.wait_for_function(
            """([selector, cols, rows]) => {
              const root = document.querySelector(selector);
              if (!root || !window.Alpine || !window.Alpine.$data) return false;
              const term = window.Alpine.$data(root)._term;
              return term && (term.cols !== cols || term.rows !== rows);
            }""",
            arg=[_STUDY_CONSOLE, wide["cols"], wide["rows"]],
            timeout=20_000,
        )
        narrow = _terminal_snapshot(page)
        assert narrow["width"] > 100 and narrow["height"] > 50
        # Full-screen TUIs commonly clear the alternate buffer before repainting
        # after SIGWINCH. A transient blank frame is fine; a pane that stays
        # blank is the user-visible failure this gate must catch.
        _wait_for_real_tui_text(page)

        before = _session_state(page)
        session_id = before.get("study_session_id")
        assert session_id, f"{agent}: no session before refresh: {before}"
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.Alpine", timeout=15_000)
        page.wait_for_function(
            """(selector) => {
              const root = document.querySelector(selector);
              if (!root || !window.Alpine || !window.Alpine.$data) return false;
              const data = window.Alpine.$data(root);
              return data && data.connected === true && data.terminalMode === 'xterm';
            }""",
            arg=_STUDY_CONSOLE,
            timeout=45_000,
        )
        _wait_for_terminal_geometry(page, timeout=30_000)
        after = _session_state(page)
        assert after.get("study_session_id") == session_id
        reattached_text = _wait_for_real_tui_text(page)
        if any(marker in reattached_text.lower() for marker in _AUTH_GATE_TEXT):
            _unavailable_harness(
                agent,
                "TUI rendered and reattached, but local harness auth is incomplete",
            )

        # Do not press Enter: this proves post-refresh keyboard input reaches
        # the real TUI without consuming provider quota or accepting a vendor
        # trust/permission prompt. Text-entry screens paint the marker; menu
        # screens (Claude's workspace trust prompt, for example) react to an
        # ArrowUp by redrawing the selected row instead.
        marker = "studylooprefreshcheck"
        before_input = _terminal_snapshot(page)["text"]
        page.locator(f"{_STUDY_CONSOLE} .xterm-mount").click()
        page.keyboard.type(marker)
        page.keyboard.press("ArrowUp")
        page.wait_for_function(
            """([selector, marker, before]) => {
              const root = document.querySelector(selector);
              if (!root || !window.Alpine || !window.Alpine.$data) return false;
              const term = window.Alpine.$data(root)._term;
              if (!term || !term.buffer) return false;
              const buffer = term.buffer.active;
              let text = '';
              for (let index = 0; index < buffer.length; index += 1) {
                const line = buffer.getLine(index);
                if (line) text += line.translateToString(true);
              }
              return text.toLowerCase().includes(marker) || text !== before;
            }""",
            arg=[_STUDY_CONSOLE, marker, before_input.replace("\n", "")],
            timeout=20_000,
        )

        reattached = _terminal_snapshot(page)
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.wait_for_function(
            """([selector, cols, rows]) => {
              const root = document.querySelector(selector);
              if (!root || !window.Alpine || !window.Alpine.$data) return false;
              const term = window.Alpine.$data(root)._term;
              return term && (term.cols !== cols || term.rows !== rows);
            }""",
            arg=[_STUDY_CONSOLE, reattached["cols"], reattached["rows"]],
            timeout=20_000,
        )
        _wait_for_real_tui_text(page)
        grown = _terminal_snapshot(page)
        assert grown["width"] > reattached["width"]
        assert grown["text"].strip(), f"{agent} TUI went blank after regrow"
        assert initial_text.strip(), f"{agent} never painted its real TUI"
    except Exception:
        page.screenshot(path=str(root / f"{agent}-rendering-failure.png"), full_page=True)
        raise
    finally:
        _end_any_active_session(page)
        context.close()
