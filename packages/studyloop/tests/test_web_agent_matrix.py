"""Per-agent parametrised Playwright tests (plan Test Strategy §Amendment #1).

Exercises the full start-session → WebSocket-handshake → Started-event
path end-to-end for each registered agent (``claude``, ``codex``,
``gemini``, ``grok``, ``kiro``, ``opencode``). Real agent binaries are not
required: the ``STUDYLOOP_TEST_AGENT_CMD`` env var stubs the PTY child
with a tiny shell snippet that prints a banner then sleeps.

The test server is started with this env var so the ``_build_pty_transport``
helper in ``web/routes/session.py`` picks it up and substitutes for the
real ``adapter.launch_cmd`` return. The hatch is stripped from the
child env by ``_build_child_env()`` so the child cannot observe its
own override key.

Plan quote (Amendment #1):
  "comprehensive Playwright sessions/testing for ALL web UI functions,
  testing all functions from ensuring the course selection using the
  correct directory structure, to each coding agent with a test prompt
  that returns the expected response"
"""

from __future__ import annotations

import os
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

from _playwright_helpers import (  # noqa: E402
    effective_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, BrowserContext, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18574

# Every agent registered in ``studyloop.agent_launcher.AGENTS`` should
# appear here. The stub command doesn't care which agent is selected —
# the point is that each agent's launch path is driven uniformly
# through ``_build_pty_transport`` without the real binary.
AGENTS = ["claude", "codex", "gemini", "grok", "kiro", "opencode"]

_STUDY_CONSOLE = '.session-terminal-area.agent-console[x-data="liveAgentConsole()"]'


def _empty_backlog(route) -> None:
    """Keep the learner's real backlog out of this hermetic start journey."""
    route.fulfill(
        json={
            "active": [],
            "parking_lot": [],
            "active_count": 0,
            "parking_lot_count": 0,
            "max_active": 3,
        }
    )


# ---------------------------------------------------------------------------
# Fixtures — server spawned with STUDYLOOP_TEST_AGENT_CMD
# ---------------------------------------------------------------------------


def _start_web_server_with_stub_agent(
    shim_dir: Path, world_root: Path
) -> subprocess.Popen:
    """Spin up a studyloop server where every PTY agent launch is a
    benign ``echo ready; cat`` that reads stdin forever.

    Isolated from the plain ``start_web_server`` in _playwright_helpers
    because the env var has to reach the child via subprocess.Popen;
    setting os.environ in the test process wouldn't survive into the
    uvicorn worker.
    """
    home = world_root / "home"
    tmp_dir = world_root / "tmp"
    state_dir = world_root / "state"
    session_dir = world_root / "session-ipc"
    plans_dir = world_root / "plans"
    vault = world_root / "vault"
    for directory in (home, tmp_dir, state_dir, session_dir, plans_dir, vault):
        directory.mkdir(parents=True, exist_ok=True)

    db_path = world_root / "sessions.db"
    config_path = world_root / "config.yaml"
    config_path.write_text(
        f"session_db: {db_path}\n"
        "content:\n"
        f"  base_path: {vault}\n"
        f"  study_paths:\n    - {vault}\n",
        encoding="utf-8",
    )
    # Complete the schema before the browser's concurrently-mounted components
    # can ask different repositories to initialise the same fresh database.
    from agent_session_tools.export_sessions import init_db

    init_db(str(db_path)).close()

    env = {
        **os.environ,
        "HOME": str(home),
        "TMPDIR": str(tmp_dir),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "STUDYLOOP_CONFIG": str(config_path),
        "STUDYLOOP_DB": str(db_path),
        "STUDYLOOP_STATE_DIR": str(state_dir),
        "STUDYLOOP_SESSION_DIR": str(session_dir),
        "STUDYLOOP_PLANS_DIR": str(plans_dir),
        "STUDYLOOP_TEST_AGENT_CMD": "echo agent-stub-ready; exec cat",
        "STUDYLOOP_KIRO_AGENTS_DIR": str(world_root / "kiro-agents"),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(WEB_PORT)]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=1).close()
            # A cold page mounts several components that read sessions.db at
            # once. Serially initialise/migrate it first so this rendering gate
            # tests the browser lifecycle rather than a first-request DB race.
            urllib.request.urlopen(
                f"http://127.0.0.1:{WEB_PORT}/api/session/state", timeout=5
            ).close()
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Test web server failed to start on port {WEB_PORT}"
    raise RuntimeError(msg)


@pytest.fixture(scope="class")
def stub_agent_server(tmp_path_factory: pytest.TempPathFactory):
    world_root = tmp_path_factory.mktemp("web-agent-matrix-world").resolve()
    shim_dir = tmp_path_factory.mktemp("web-agent-matrix-binaries")
    for binary in ("claude", "codex", "gemini", "grok", "kiro-cli", "opencode"):
        shim = shim_dir / binary
        shim.write_text("#!/bin/sh\necho agent-shim-ready\nexec cat\n")
        shim.chmod(0o755)
    proc = _start_web_server_with_stub_agent(shim_dir, world_root)
    try:
        yield proc
    finally:
        # Make sure we end any active session before tearing the server
        # down — the active-session singleton would otherwise linger.
        user, password = effective_credentials()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{WEB_PORT}/api/session/end",
                method="POST",
            )
            if password:
                import base64

                creds = base64.b64encode(f"{user}:{password}".encode()).decode()
                req.add_header("Authorization", f"Basic {creds}")
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stderr:
            err = proc.stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                print("\n--- stub agent server stderr ---\n" + err, flush=True)


@pytest.fixture()
def agent_auth_context(browser: Browser) -> Generator[BrowserContext, None, None]:
    user, password = effective_credentials()
    ctx_args = {}
    if password:
        ctx_args["http_credentials"] = {"username": user, "password": password}
    context = browser.new_context(**ctx_args)
    try:
        yield context
    finally:
        context.close()


@pytest.fixture()
def agent_page(
    stub_agent_server, agent_auth_context: BrowserContext
) -> Generator[Page, None, None]:
    _ = stub_agent_server  # keep the fixture alive
    page = agent_auth_context.new_page()
    try:
        yield page
    finally:
        page.close()


def _end_any_active_session(page: Page) -> None:
    """Best-effort cleanup between parametrised cases — the single-session
    singleton would otherwise 409 on the next start.

    Uses in-page fetch() so the browser's auth context is carried along
    (Playwright's APIRequestContext doesn't always share HTTP Basic Auth
    with the BrowserContext when it was set via ``http_credentials``).
    """
    try:
        # The page may not have navigated yet; goto root first to pin the origin.
        if not page.url.startswith(f"http://127.0.0.1:{WEB_PORT}"):
            page.goto(f"http://127.0.0.1:{WEB_PORT}/")
            page.wait_for_load_state("domcontentloaded")
        page.evaluate(
            """async () => {
              try { await fetch('/api/session/end', {method: 'POST'}); }
              catch {}
            }"""
        )
        # Give the teardown a moment to release the active singleton.
        page.wait_for_timeout(150)
    except Exception:
        pass


def _terminal_snapshot(page: Page) -> dict:
    """Read the stock xterm surface that the learner can actually see.

    xterm paints glyphs to a canvas, so DOM text assertions cannot prove that
    output survived a fit/repaint. Its public buffer plus canvas geometry are
    the closest deterministic representation of the rendered terminal.
    """
    snapshot = page.evaluate(
        """(selector) => {
          const root = document.querySelector(selector);
          if (!root || !window.Alpine || !window.Alpine.$data) return null;
          const data = window.Alpine.$data(root);
          const term = data && data._term;
          if (!term || !term.buffer) return null;
          const buffer = term.buffer.active;
          let text = '';
          for (let index = 0; index < buffer.length; index += 1) {
            const line = buffer.getLine(index);
            if (line) text += line.translateToString(true) + '\\n';
          }
          const painted = root.querySelector('.xterm-screen')
            || root.querySelector('.xterm canvas')
            || root.querySelector('.xterm');
          const rect = painted && painted.getBoundingClientRect();
          return {
            connected: data.connected,
            status: data.status,
            cols: term.cols,
            rows: term.rows,
            width: rect ? rect.width : 0,
            height: rect ? rect.height : 0,
            text,
          };
        }""",
        _STUDY_CONSOLE,
    )
    assert snapshot is not None, "the Study Session xterm surface was not mounted"
    return snapshot


def _wait_for_terminal_text(page: Page, needle: str, *, timeout: int = 30_000) -> None:
    page.wait_for_function(
        """([selector, needle]) => {
          const root = document.querySelector(selector);
          if (!root || !window.Alpine || !window.Alpine.$data) return false;
          const data = window.Alpine.$data(root);
          const term = data && data._term;
          if (!term || !term.buffer) return false;
          const buffer = term.buffer.active;
          let text = '';
          for (let index = 0; index < buffer.length; index += 1) {
            const line = buffer.getLine(index);
            if (line) text += line.translateToString(true) + '\\n';
          }
          return text.includes(needle);
        }""",
        arg=[_STUDY_CONSOLE, needle],
        timeout=timeout,
    )


def _wait_for_terminal_geometry(page: Page, *, timeout: int = 15_000) -> None:
    """Wait until the learner-facing xterm is laid out and paintable."""
    page.wait_for_function(
        """(selector) => {
          const root = document.querySelector(selector);
          if (!root) return false;
          const painted = root.querySelector('.xterm-screen')
            || root.querySelector('.xterm canvas')
            || root.querySelector('.xterm');
          if (!painted) return false;
          const rect = painted.getBoundingClientRect();
          return rect.width > 100 && rect.height > 50;
        }""",
        arg=_STUDY_CONSOLE,
        timeout=timeout,
    )


def _type_into_study_terminal(page: Page, text: str) -> None:
    """Exercise the real browser-keyboard -> xterm -> WS -> PTY input path."""
    page.locator(f"{_STUDY_CONSOLE} .xterm-mount").click()
    page.keyboard.type(text)
    page.keyboard.press("Enter")


def _session_state(page: Page) -> dict:
    return page.evaluate(
        "async () => (await fetch('/api/session/state', {cache: 'no-store'})).json()"
    )


# ---------------------------------------------------------------------------
# Per-agent matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
class TestAgentMatrix:
    """Each agent launches cleanly through the PTY stub and emits
    ``Started`` over the WebSocket."""

    def test_start_session_returns_ws_url(self, agent_page: Page, agent: str) -> None:
        """POST /api/session/start with each agent returns a 201 + ws_url."""
        _end_any_active_session(agent_page)
        agent_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        agent_page.wait_for_load_state("domcontentloaded")
        result = agent_page.evaluate(
            """async (agent) => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `Test ${agent}`,
                  energy: 5,
                  agent: agent,
                  transport: 'pty',
                }),
              });
              return {status: res.status, body: await res.json()};
            }""",
            agent,
        )
        assert result["status"] == 201, f"agent={agent}: got {result}"
        body = result["body"]
        assert body["agent"] == agent
        assert body["transport"] == "pty"
        assert body["ws_url"].startswith(
            f"/api/session/ws?study_session_id={body['study_session_id']}"
        )
        _end_any_active_session(agent_page)

    def test_websocket_emits_started_event(self, agent_page: Page, agent: str) -> None:
        """Opening the returned ws_url receives a Started(agent=<agent>) frame."""
        _end_any_active_session(agent_page)
        # Load the app so window.WebSocket + auth cookies are available.
        agent_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        agent_page.wait_for_load_state("domcontentloaded")

        frame = agent_page.evaluate(
            """async (agent) => {
              const startRes = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `WS ${agent}`, energy: 5, agent, transport: 'pty',
                }),
              });
              if (!startRes.ok) return {error: 'start failed', status: startRes.status};
              const data = await startRes.json();
              const wsUrl = `ws://${window.location.host}${data.ws_url}`;
              return await new Promise((resolve) => {
                const ws = new WebSocket(wsUrl);
                let done = false;
                const timer = setTimeout(() => {
                  if (done) return;
                  done = true;
                  try { ws.close(); } catch {}
                  resolve({error: 'timeout'});
                }, 10000);
                ws.addEventListener('message', (e) => {
                  if (done) return;
                  if (typeof e.data === 'string') {
                    try {
                      const frame = JSON.parse(e.data);
                      if (frame.type === 'started') {
                        done = true;
                        clearTimeout(timer);
                        try { ws.close(); } catch {}
                        resolve({frame});
                      }
                    } catch {}
                  }
                });
                ws.addEventListener('error', () => {
                  if (done) return;
                  done = true;
                  clearTimeout(timer);
                  resolve({error: 'ws error'});
                });
              });
            }""",
            agent,
        )
        assert frame.get("error") is None, f"agent={agent}: {frame}"
        assert frame["frame"]["type"] == "started"
        assert frame["frame"]["agent"] == agent
        _end_any_active_session(agent_page)

    def test_websocket_streams_output_bytes(self, agent_page: Page, agent: str) -> None:
        """The stub command prints ``agent-stub-ready`` then tails stdin;
        the WebSocket should emit binary frames carrying that banner
        once the PTY is up."""
        _end_any_active_session(agent_page)
        agent_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        agent_page.wait_for_load_state("domcontentloaded")

        bytes_seen = agent_page.evaluate(
            """async (agent) => {
              const startRes = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `Bytes ${agent}`, energy: 5, agent, transport: 'pty',
                }),
              });
              if (!startRes.ok) return {error: 'start failed'};
              const data = await startRes.json();
              const wsUrl = `ws://${window.location.host}${data.ws_url}`;
              return await new Promise((resolve) => {
                const ws = new WebSocket(wsUrl);
                ws.binaryType = 'arraybuffer';
                let text = '';
                const finish = (reason) => {
                  try { ws.close(); } catch {}
                  resolve({text, reason});
                };
                const timer = setTimeout(() => finish('timeout'), 10000);
                ws.addEventListener('message', (e) => {
                  if (e.data instanceof ArrayBuffer) {
                    text += new TextDecoder().decode(new Uint8Array(e.data));
                    if (text.includes('agent-stub-ready')) {
                      clearTimeout(timer);
                      finish('matched');
                    }
                  }
                });
                ws.addEventListener('error', () => {
                  clearTimeout(timer);
                  finish('error');
                });
              });
            }""",
            agent,
        )
        assert bytes_seen.get("reason") == "matched", f"agent={agent}: {bytes_seen}"
        assert "agent-stub-ready" in bytes_seen["text"]
        _end_any_active_session(agent_page)

    def test_stock_terminal_survives_resize_refresh_and_reattach(
        self, agent_page: Page, agent: str
    ) -> None:
        """Release gate: every public harness works through the stock terminal.

        This deliberately starts through the learner-facing picker, then proves
        visible output, a real dimension change, retained output, bidirectional
        input, stable session identity over refresh, automatic reattachment,
        post-refresh input, and a second fit at a larger viewport.
        """
        _end_any_active_session(agent_page)
        agent_page.set_viewport_size({"width": 1440, "height": 900})
        agent_page.route("**/api/backlog", _empty_backlog)

        try:
            agent_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
            agent_page.wait_for_function("() => !!window.Alpine", timeout=15_000)
            agent_page.get_by_role("button", name="Study Session", exact=True).click()
            agent_page.locator("#topic-input").wait_for(state="visible", timeout=15_000)
            agent_page.locator("#topic-input").fill(f"Lifecycle {agent}")
            agent_page.wait_for_function(
                """(agent) => {
                  const select = document.querySelector('#agent-select');
                  return select && [...select.options].some(
                    (option) => option.value === agent && !option.disabled
                  );
                }""",
                arg=agent,
                timeout=45_000,
            )
            agent_page.select_option("#agent-select", value=agent)
            assert agent_page.locator("#transport-select").input_value() == "pty"
            agent_page.locator(".study-start-picker .start-session-btn").click()

            agent_page.wait_for_function(
                """(selector) => {
                  const root = document.querySelector(selector);
                  if (!root || !window.Alpine || !window.Alpine.$data) return false;
                  const data = window.Alpine.$data(root);
                  return data && data.connected === true && data.terminalMode === 'xterm';
                }""",
                arg=_STUDY_CONSOLE,
                timeout=30_000,
            )
            _wait_for_terminal_geometry(agent_page)
            _wait_for_terminal_text(agent_page, "agent-stub-ready")
            wide = _terminal_snapshot(agent_page)
            assert wide["connected"] is True
            assert wide["cols"] > 0 and wide["rows"] > 0
            assert wide["width"] > 100 and wide["height"] > 50

            # Shrink far enough to force FitAddon to choose a new PTY size.
            agent_page.set_viewport_size({"width": 820, "height": 560})
            agent_page.wait_for_function(
                """([selector, cols, rows]) => {
                  const root = document.querySelector(selector);
                  if (!root || !window.Alpine || !window.Alpine.$data) return false;
                  const term = window.Alpine.$data(root)._term;
                  return term && (term.cols !== cols || term.rows !== rows);
                }""",
                arg=[_STUDY_CONSOLE, wide["cols"], wide["rows"]],
                timeout=15_000,
            )
            small = _terminal_snapshot(agent_page)
            assert small["width"] > 100 and small["height"] > 50
            assert "agent-stub-ready" in small["text"], (
                f"agent={agent}: resize repainted an empty terminal"
            )

            before_refresh_marker = f"before-refresh-{agent}"
            _type_into_study_terminal(agent_page, before_refresh_marker)
            _wait_for_terminal_text(agent_page, before_refresh_marker)

            before = _session_state(agent_page)
            session_id = before.get("study_session_id")
            assert session_id, f"agent={agent}: no active session before refresh: {before}"

            # Reload while narrow: adoption must mount a freshly-sized terminal
            # and reattach it to the same server-side PTY without a user click.
            agent_page.reload()
            agent_page.wait_for_load_state("domcontentloaded")
            agent_page.wait_for_function("() => !!window.Alpine", timeout=15_000)
            agent_page.wait_for_function(
                """(selector) => {
                  const root = document.querySelector(selector);
                  if (!root || !window.Alpine || !window.Alpine.$data) return false;
                  const data = window.Alpine.$data(root);
                  return data && data.connected === true && data.terminalMode === 'xterm';
                }""",
                arg=_STUDY_CONSOLE,
                timeout=30_000,
            )
            _wait_for_terminal_geometry(agent_page)
            after = _session_state(agent_page)
            assert after.get("study_session_id") == session_id, (
                f"agent={agent}: refresh replaced or lost the session: {before} -> {after}"
            )
            reattached = _terminal_snapshot(agent_page)
            assert reattached["width"] > 100 and reattached["height"] > 50
            assert "Starting" not in reattached["status"]

            after_refresh_marker = f"after-refresh-{agent}"
            _type_into_study_terminal(agent_page, after_refresh_marker)
            _wait_for_terminal_text(agent_page, after_refresh_marker)

            # Grow again after reattachment. The post-refresh marker must stay
            # rendered while FitAddon changes dimensions a second time.
            narrow_dims = (reattached["cols"], reattached["rows"])
            agent_page.set_viewport_size({"width": 1600, "height": 1000})
            agent_page.wait_for_function(
                """([selector, cols, rows]) => {
                  const root = document.querySelector(selector);
                  if (!root || !window.Alpine || !window.Alpine.$data) return false;
                  const term = window.Alpine.$data(root)._term;
                  return term && (term.cols !== cols || term.rows !== rows);
                }""",
                arg=[_STUDY_CONSOLE, *narrow_dims],
                timeout=15_000,
            )
            regrown = _terminal_snapshot(agent_page)
            assert regrown["width"] > reattached["width"]
            assert regrown["height"] > 50
            assert after_refresh_marker in regrown["text"], (
                f"agent={agent}: post-refresh output vanished on regrow"
            )
        finally:
            _end_any_active_session(agent_page)
