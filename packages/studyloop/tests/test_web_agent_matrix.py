"""Per-agent parametrised Playwright tests (plan Test Strategy §Amendment #1).

Exercises the full start-session → WebSocket-handshake → Started-event
path end-to-end for every harness in ``RELEASE_HARNESSES``. Real agent
binaries are not required: the ``STUDYLOOP_TEST_AGENT_CMD`` env var stubs
the PTY child with a tiny shell snippet that prints a banner then sleeps.

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

import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

import pytest

from studyloop.harnesses import RELEASE_HARNESSES

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    clean_ipc,
    effective_credentials,
    start_web_server,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, BrowserContext, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18574

# Derived from the release contract, so a harness added to or dropped from
# ``RELEASE_HARNESSES`` cannot silently keep or lose coverage here. The stub
# command doesn't care which agent is selected — the point is that each
# agent's launch path is driven uniformly through ``_build_pty_transport``
# without the real binary.
AGENTS = list(RELEASE_HARNESSES)


# ---------------------------------------------------------------------------
# Fixtures — server spawned with STUDYLOOP_TEST_AGENT_CMD
# ---------------------------------------------------------------------------


def _start_web_server_with_stub_agent() -> subprocess.Popen:
    """Spin up a studyloop server where every PTY agent launch is a
    benign ``echo ready; cat`` that reads stdin forever.

    C13/R-49g: routed through the shared ``start_web_server`` (which now
    builds a hermetic child env and refuses to spawn against the
    developer's real HOME/config dir) instead of a hand-rolled
    ``env = {**os.environ, ...}`` + polling loop -- the env var still
    reaches the child via ``extra_env``, same as before.
    """
    return start_web_server(
        WEB_PORT, extra_env={"STUDYLOOP_TEST_AGENT_CMD": "echo agent-stub-ready; exec cat"}
    )


@pytest.fixture(scope="class")
def stub_agent_server():
    clean_ipc()
    proc = _start_web_server_with_stub_agent()
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
        clean_ipc()


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
