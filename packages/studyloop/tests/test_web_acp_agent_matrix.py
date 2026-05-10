"""Per-ACP-agent parametrised Playwright tests (plan §2.3 — Amendment #11).

Mirrors ``test_web_agent_matrix.py`` but for the ACP transport:

- Parametrised over Kiro + Gemini (the two ``supports_acp: true`` agents
  registered in ``studyloop.agent_launcher.AGENTS``).
- Drives the route through ``STUDYLOOP_TEST_ACP_CMD`` pointing at the
  scripted ``_stub_acp_agent.py`` so no real Kiro / Gemini binary is
  needed.
- Asserts: (1) ``POST /session/start`` with ``transport=acp`` returns
  201 + ws_url, (2) opening the ws receives ``Started(agent=<name>)``
  over the WS, (3) sending a text ``input`` frame triggers an
  ``agent_message(kind=agent_chunk)`` frame carrying the stub's
  scripted text.

Port **18575** — the plan allocates one port per e2e test file
(18570 nav, 18571 review, 18572 lifecycle, 18573 stores, 18574 PTY
matrix, 18575 here).

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §2.3
"""

from __future__ import annotations

import json
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

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from _playwright_helpers import (  # noqa: E402
    clean_ipc,
    effective_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, BrowserContext, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18575

# Both agents advertise ``supports_acp: true`` in ``/session/options``.
ACP_AGENTS = ["kiro", "gemini"]

# Scripted prompt response — a single ``agent_message_chunk`` with a
# known text payload, then ``stop_reason=end_turn``. The transport
# should surface this as an ``AgentMessage(kind="agent_chunk")`` event.
_CHUNK_TEXT = "pong-from-stub"
_STUB_PROMPT_UPDATES = [
    {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "stub-session-1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": _CHUNK_TEXT},
            },
        },
    }
]


def _stub_acp_cmd() -> str:
    """Return a shell-free argv string suitable for STUDYLOOP_TEST_ACP_CMD.

    ``sys.executable`` may contain spaces (e.g. macOS ``Application
    Support``); quote with shlex.quote via json.dumps to keep things
    safe. The route uses ``shlex.split`` on this value.
    """
    stub = _tests_dir / "_stub_acp_agent.py"
    # shlex.join would be cleaner but needs Python 3.8+; json.dumps
    # quotes consistently and the route parses with shlex.split.
    return f'"{sys.executable}" "{stub}"'


def _start_web_server_with_stub_acp() -> subprocess.Popen:
    """Spin up a studyloop server where ACP launches route through the stub.

    Environment contract:
    - STUDYLOOP_TEST_ACP_CMD: argv the route spawns instead of kiro-cli/gemini.
    - STUB_ACP_PROMPT_UPDATES: scripted session/update notification flow.
    - STUB_ACP_PROMPT_STOP_REASON: stopReason returned after the notification.
    """
    env = {
        **os.environ,
        "STUDYLOOP_TEST_ACP_CMD": _stub_acp_cmd(),
        "STUB_ACP_PROMPT_UPDATES": json.dumps(_STUB_PROMPT_UPDATES),
        "STUB_ACP_PROMPT_STOP_REASON": "end_turn",
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
            urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=1)
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
def stub_acp_server():
    clean_ipc()
    proc = _start_web_server_with_stub_acp()
    try:
        yield proc
    finally:
        # Best-effort end-session so the singleton doesn't linger.
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
                print("\n--- stub ACP agent server stderr ---\n" + err, flush=True)
        clean_ipc()


@pytest.fixture()
def acp_auth_context(browser: Browser) -> Generator[BrowserContext, None, None]:
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
def acp_page(stub_acp_server, acp_auth_context: BrowserContext) -> Generator[Page, None, None]:
    _ = stub_acp_server  # keep the fixture alive
    page = acp_auth_context.new_page()
    try:
        yield page
    finally:
        page.close()


def _end_any_active_session(page: Page) -> None:
    """Best-effort cleanup between parametrised cases — same shape as PTY matrix."""
    try:
        if not page.url.startswith(f"http://127.0.0.1:{WEB_PORT}"):
            page.goto(f"http://127.0.0.1:{WEB_PORT}/")
            page.wait_for_load_state("domcontentloaded")
        page.evaluate(
            """async () => {
              try { await fetch('/api/session/end', {method: 'POST'}); }
              catch {}
            }"""
        )
        page.wait_for_timeout(150)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Per-ACP-agent matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", ACP_AGENTS)
class TestAcpAgentMatrix:
    """Each ACP agent launches cleanly through the scripted stub and
    emits Started + an agent_message frame over the WebSocket."""

    def test_acp_start_returns_ws_url(self, acp_page: Page, agent: str) -> None:
        """POST /api/session/start with each ACP agent returns 201 + ws_url."""
        _end_any_active_session(acp_page)
        acp_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        acp_page.wait_for_load_state("domcontentloaded")
        result = acp_page.evaluate(
            """async (agent) => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `Test ACP ${agent}`,
                  energy: 5,
                  agent: agent,
                  transport: 'acp',
                }),
              });
              return {status: res.status, body: await res.json()};
            }""",
            agent,
        )
        assert result["status"] == 201, f"agent={agent}: got {result}"
        body = result["body"]
        assert body["agent"] == agent
        assert body["transport"] == "acp"
        assert body["ws_url"].startswith(
            f"/api/session/ws?study_session_id={body['study_session_id']}"
        )
        _end_any_active_session(acp_page)

    def test_websocket_emits_started_event(self, acp_page: Page, agent: str) -> None:
        """Opening the returned ws_url receives a Started frame naming the stub agent."""
        _end_any_active_session(acp_page)
        acp_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        acp_page.wait_for_load_state("domcontentloaded")

        frame = acp_page.evaluate(
            """async (agent) => {
              const startRes = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `WS ACP ${agent}`, energy: 5, agent, transport: 'acp',
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
        # The stub reports agent name "Stub ACP Agent" via agentInfo.name.
        assert frame["frame"]["agent"] == "Stub ACP Agent"
        _end_any_active_session(acp_page)

    def test_websocket_emits_agent_message_chunk(self, acp_page: Page, agent: str) -> None:
        """Sending a text input frame triggers an agent_message chunk with the stub's text."""
        _end_any_active_session(acp_page)
        acp_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        acp_page.wait_for_load_state("domcontentloaded")

        result = acp_page.evaluate(
            """async (agent) => {
              const startRes = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: `Chunk ACP ${agent}`, energy: 5, agent, transport: 'acp',
                }),
              });
              if (!startRes.ok) return {error: 'start failed', status: startRes.status};
              const data = await startRes.json();
              const wsUrl = `ws://${window.location.host}${data.ws_url}`;
              return await new Promise((resolve) => {
                const ws = new WebSocket(wsUrl);
                let gotStarted = false;
                let done = false;
                const finish = (payload) => {
                  if (done) return;
                  done = true;
                  try { ws.close(); } catch {}
                  resolve(payload);
                };
                const timer = setTimeout(() => finish({error: 'timeout'}), 10000);
                ws.addEventListener('open', () => {
                  // Wait for Started, then send input.
                });
                ws.addEventListener('message', (e) => {
                  if (typeof e.data !== 'string') return;
                  let frame;
                  try { frame = JSON.parse(e.data); } catch { return; }
                  if (frame.type === 'started' && !gotStarted) {
                    gotStarted = true;
                    ws.send(JSON.stringify({type: 'input', data: 'ping'}));
                    return;
                  }
                  if (frame.type === 'agent_message' && frame.kind === 'agent_chunk') {
                    clearTimeout(timer);
                    finish({frame});
                  }
                });
                ws.addEventListener('error', () => {
                  clearTimeout(timer);
                  finish({error: 'ws error'});
                });
              });
            }""",
            agent,
        )
        assert result.get("error") is None, f"agent={agent}: {result}"
        payload = result["frame"]["payload"]
        # Normaliser surfaces the chunk payload as-is under ``payload``.
        # The stub script plants ``_CHUNK_TEXT`` in ``content.text``.
        text = _extract_chunk_text(payload)
        assert text == "pong-from-stub", f"agent={agent}: payload={payload!r}"
        _end_any_active_session(acp_page)


def _extract_chunk_text(payload: dict) -> str:
    """Dig the text out of an agent_chunk payload.

    The ACP normaliser passes the ``update`` subtree through with some
    massaging; the content can live under ``content.text`` or
    ``content.0.text`` depending on the stub format. Try both.
    """
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    if isinstance(content, dict):
        return content.get("text", "")
    if isinstance(content, list) and content and isinstance(content[0], dict):
        return content[0].get("text", "")
    # Fallback: some normalisers may have already flattened it.
    return payload.get("text", "")
