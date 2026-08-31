"""Per-ACP-agent parametrised Playwright tests (plan §2.3 — Amendment #11).

Mirrors ``test_web_agent_matrix.py`` but for the ACP transport:

- Parametrised over Kiro + Gemini + Grok (the ``supports_acp: true`` agents
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

from studyloop.web.services.session_start import ACP_CAPABLE_AGENTS

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

# These agents advertise ``supports_acp: true`` in ``/session/options``.
# Derived from the server's own capability set, never hand-listed. The
# previous literal was ["kiro", "gemini", "grok"]: gemini and grok were
# dropped from the release contract, so /api/session/start rejects them with
# a 400 naming supported_agents, and every parametrisation over them failed
# while asserting success — 62 failures across these two files.
ACP_AGENTS = sorted(ACP_CAPABLE_AGENTS)

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


# ---------------------------------------------------------------------------
# U7: agent_chunk payload text renders into the ACP chat surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", ACP_AGENTS)
class TestAcpChatChunkRenders:
    """agent_chunk payload text reaches the ACP chat surface (.acp-message.assistant).

    Replaces the former xterm-buffer poll (PR-D) which broke in U2 when
    ACP sessions no longer mount xterm.  The chat panel (U2+) is now the
    canonical surface for ACP output.  Parametrised over kiro + gemini —
    the normaliser is agent-agnostic so both must pass.
    """

    def test_agent_chunk_text_appears_in_chat(self, acp_page: Page, agent: str) -> None:
        _end_any_active_session(acp_page)
        acp_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        acp_page.wait_for_load_state("domcontentloaded")
        acp_page.wait_for_function("() => !!window.Alpine", timeout=5000)

        start_body = acp_page.evaluate(
            """async (agent) => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'U7 chat chunk', energy: 5, agent: agent, transport: 'acp',
                }),
              });
              return {status: res.status, body: await res.json()};
            }""",
            agent,
        )
        assert start_body["status"] == 201, f"agent={agent}: {start_body}"

        acp_page.evaluate(
            """(data) => {
              const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
              if (timerRoot) {
                const d = window.Alpine.$data(timerRoot);
                d.sessionActive = true;
                d.topic = 'U7 chat chunk';
                d.startTime = new Date();
              }
              return new Promise((resolve) => setTimeout(() => {
                window.dispatchEvent(new CustomEvent('study-session-start', {
                  detail: {
                    topic: 'U7 chat chunk',
                    energy: 5,
                    sessionType: 'study',
                    targetKind: 'topic',
                    targetPath: null,
                    agent: data.agent,
                    resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport,
                    wsUrl: data.ws_url,
                  },
                }));
                resolve();
              }, 50));
            }""",
            start_body["body"],
        )

        # Wait until the WS is open and the ACP chat mode is active.
        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return d && d.connected === true && d.terminalMode === 'acp-chat';
              } catch { return false; }
            }""",
            timeout=10000,
        )

        # Send one input turn via the WS.
        acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              const d = window.Alpine.$data(root);
              const ws = d._ws;
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'input', data: 'ping'}));
              }
            }"""
        )

        # The stub's chunk text must appear in an assistant bubble on the
        # chat surface — the canonical ACP output location since U2.
        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return (d.acpMessages || []).some(
                  m => m.role === 'assistant' && (m.text || '').includes('pong-from-stub')
                );
              } catch { return false; }
            }""",
            timeout=10000,
        )
        _end_any_active_session(acp_page)


# ---------------------------------------------------------------------------
# PR-E: ACP turn-based input row drives session/prompt and locks during turn
# ---------------------------------------------------------------------------


class TestAcpInputRow:
    """ACP transport renders a dedicated input row beneath the xterm.
    Submitting it sends a single ``{type: 'input'}`` frame (one ACP turn)
    rather than per-keystroke frames, echoes the message into xterm, and
    locks the field until ``turn_end`` arrives.
    """

    def _start_acp_session_in_dom(self, page: Page) -> None:
        """Drive the page into an active ACP session against the stub.

        Same flow as ``TestAgentChunkRendersInXterm`` but factored out so
        each test in this class starts from a wired-up session without
        copy-pasting the bypass-the-picker dance.
        """
        _end_any_active_session(page)
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)
        start_body = page.evaluate(
            """async () => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'PR-E input row', energy: 5,
                  agent: 'kiro', transport: 'acp',
                }),
              });
              return {status: res.status, body: await res.json()};
            }"""
        )
        assert start_body["status"] == 201, start_body
        page.evaluate(
            """(data) => {
              const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
              if (timerRoot) {
                const d = window.Alpine.$data(timerRoot);
                d.sessionActive = true;
                d.topic = 'PR-E input row';
                d.startTime = new Date();
              }
              return new Promise((resolve) => setTimeout(() => {
                window.dispatchEvent(new CustomEvent('study-session-start', {
                  detail: {
                    topic: 'PR-E input row', energy: 5,
                    sessionType: 'study', targetKind: 'topic',
                    targetPath: null,
                    agent: data.agent, resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport, wsUrl: data.ws_url,
                  },
                }));
                resolve();
              }, 50));
            }""",
            start_body["body"],
        )
        page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              const d = window.Alpine.$data(root);
              return d && d.connected === true && d.transport === 'acp';
            }""",
            timeout=10000,
        )

    def test_input_row_visible_for_acp(self, acp_page: Page) -> None:
        """ACP session shows the .acp-input-row when transport === 'acp'."""
        self._start_acp_session_in_dom(acp_page)
        # Assert the form's own x-show evaluates true — i.e. the form has
        # NOT been collapsed by Alpine's display:none. Ancestor view
        # containers (e.g. nav routing) may stay hidden in the test
        # harness because we bypass the picker; the contract this test
        # protects is just "form gets revealed when transport='acp'".
        result = acp_page.evaluate(
            """() => {
              const form = document.querySelector('.acp-input-row');
              if (!form) return {error: 'no .acp-input-row'};
              return {
                inlineDisplay: form.style.display || '',
                hasHiddenStyle: form.style.display === 'none',
              };
            }"""
        )
        assert result.get("error") is None, result
        assert not result["hasHiddenStyle"], (
            f"acp-input-row collapsed by x-show: inlineDisplay={result['inlineDisplay']!r}"
        )
        _end_any_active_session(acp_page)

    def test_submit_blocks_concurrent_turns(self, acp_page: Page) -> None:
        """While a turn is in flight, the field is disabled — second
        Enter must not fire a second ACP turn (Kiro rejects mid-flight
        prompts which surfaced as 'Internal error' in S689)."""
        self._start_acp_session_in_dom(acp_page)
        acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              const d = window.Alpine.$data(root);
              const ws = d._ws;
              window.__sentInputs = [];
              const origSend = ws.send.bind(ws);
              ws.send = (payload) => {
                try {
                  const parsed = JSON.parse(payload);
                  if (parsed && parsed.type === 'input') {
                    window.__sentInputs.push(parsed.data);
                  }
                } catch {}
                return origSend(payload);
              };
              // Hold acpSending true so the second submit attempt is blocked
              // by both the form's disabled state AND _sendAcpInput's guard.
              d.acpSending = true;
            }"""
        )

        # Trying to type into a disabled input throws in Playwright; use
        # the underlying _sendAcpInput method directly to exercise the
        # in-method guard, then assert nothing went out.
        acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              const d = window.Alpine.$data(root);
              d.acpInput = 'should-not-send';
              d._sendAcpInput();
            }"""
        )
        sent = acp_page.evaluate("() => window.__sentInputs")
        assert sent == [], f"expected zero input frames during locked turn, got {sent!r}"
        _end_any_active_session(acp_page)


# ---------------------------------------------------------------------------
# U2: ACP chat panel mount — visibility branching + state lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestU2ChatPanelMount:
    """U2 scaffolding: the new .acp-chat-panel mounts for ACP transport,
    .xterm-panel mounts for PTY, and state tears down cleanly on stop().

    All tests run against the stub ACP server (class-scoped).  The stub
    always starts with transport=acp so we can exercise the new path
    without a real Kiro binary.
    """

    def _activate_session(self, page: Page, transport: str = "acp", agent: str = "kiro") -> None:
        """Drive the page into a live session via the bypass-the-picker
        flow used in earlier test classes, parametrised on transport."""
        _end_any_active_session(page)
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)

        start_body = page.evaluate(
            """async ([agent, transport]) => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'U2 test', energy: 5, agent, transport,
                }),
              });
              return {status: res.status, body: await res.json()};
            }""",
            [agent, transport],
        )
        assert start_body["status"] == 201, start_body

        page.evaluate(
            """(data) => {
              const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
              if (timerRoot) {
                const d = window.Alpine.$data(timerRoot);
                d.sessionActive = true;
                d.topic = 'U2 test';
                d.startTime = new Date();
              }
              return new Promise((resolve) => setTimeout(() => {
                window.dispatchEvent(new CustomEvent('study-session-start', {
                  detail: {
                    topic: 'U2 test', energy: 5,
                    sessionType: 'study', targetKind: 'topic',
                    targetPath: null,
                    agent: data.agent, resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport, wsUrl: data.ws_url,
                  },
                }));
                resolve();
              }, 50));
            }""",
            start_body["body"],
        )

        # Wait for liveAgentConsole to process the event and set terminalMode.
        # Playwright's wait_for_function requires the arg as a keyword.
        page.wait_for_function(
            """(transport) => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return d && d.transport === transport;
              } catch { return false; }
            }""",
            arg=transport,
            timeout=10000,
        )

    def test_acp_transport_shows_chat_panel_hides_xterm(self, acp_page: Page) -> None:
        """Starting an ACP session sets terminalMode='acp-chat': the
        .acp-chat-panel becomes visible and .xterm-panel is hidden."""
        self._activate_session(acp_page, transport="acp")

        # Confirm terminalMode via Alpine data (not DOM visibility, which
        # requires the ancestor sessionActive view to be shown — bypassed
        # in the test harness).
        terminal_mode = acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return null;
              try { return window.Alpine.$data(root).terminalMode; }
              catch { return null; }
            }"""
        )
        assert terminal_mode == "acp-chat", (
            f"expected terminalMode='acp-chat', got {terminal_mode!r}"
        )

        # Check Alpine x-show binding: the panel whose x-show evaluates
        # true must be .acp-chat-panel; .xterm-panel must be hidden.
        # We read the inline style that Alpine writes (display:none = hidden).
        panel_states = acp_page.evaluate(
            """() => {
              const chat = document.querySelector('.acp-chat-panel');
              const xterm = document.querySelector('.xterm-panel');
              return {
                chatHidden: chat ? chat.style.display === 'none' : null,
                xtermHidden: xterm ? xterm.style.display === 'none' : null,
              };
            }"""
        )
        assert panel_states["chatHidden"] is False, (
            f".acp-chat-panel should be visible: {panel_states}"
        )
        assert panel_states["xtermHidden"] is True, f".xterm-panel should be hidden: {panel_states}"
        _end_any_active_session(acp_page)

    def test_pty_transport_shows_xterm_hides_chat_panel(self, acp_page: Page) -> None:
        """Starting a PTY session sets terminalMode='xterm': .xterm-panel
        visible, .acp-chat-panel hidden."""
        # The stub server only supports ACP; PTY sessions spin up a real
        # PTY which the stub server doesn't configure.  We can still fire
        # a pty-transport start event without a valid wsUrl to verify that
        # the branch executes _mountXterm (falling through to legacy iframe
        # when wsUrl is absent) rather than _mountAcpChat.  The key
        # invariant here is terminalMode !== 'acp-chat'.
        _end_any_active_session(acp_page)
        acp_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        acp_page.wait_for_load_state("domcontentloaded")
        acp_page.wait_for_function("() => !!window.Alpine", timeout=5000)

        # Flip sessionActive so the agent-console mounts.
        acp_page.evaluate(
            """() => {
              const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
              if (timerRoot) {
                const d = window.Alpine.$data(timerRoot);
                d.sessionActive = true;
                d.startTime = new Date();
              }
              return new Promise((resolve) => setTimeout(() => {
                // Dispatch with transport='pty' but no wsUrl — triggers
                // _mountLegacyIframe (the else branch), never _mountAcpChat.
                window.dispatchEvent(new CustomEvent('study-session-start', {
                  detail: {
                    topic: 'U2 PTY test', energy: 5,
                    sessionType: 'study', targetKind: 'topic',
                    targetPath: null,
                    agent: 'kiro', resolvedAgent: 'kiro',
                    studySessionId: 'u2-pty-test',
                    transport: 'pty',
                    wsUrl: null,  // no wsUrl → legacy iframe branch
                  },
                }));
                resolve();
              }, 50));
            }"""
        )

        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return d && d.terminalMode !== null;
              } catch { return false; }
            }""",
            timeout=5000,
        )

        terminal_mode = acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return null;
              try { return window.Alpine.$data(root).terminalMode; }
              catch { return null; }
            }"""
        )
        # Must NOT be 'acp-chat' — either 'xterm' or 'ttyd-iframe'
        assert terminal_mode != "acp-chat", (
            f"PTY transport must not produce terminalMode='acp-chat', got {terminal_mode!r}"
        )

        chat_hidden = acp_page.evaluate(
            """() => {
              const el = document.querySelector('.acp-chat-panel');
              return el ? el.style.display === 'none' : null;
            }"""
        )
        assert chat_hidden is True, (
            f".acp-chat-panel should be hidden for PTY transport: chatHidden={chat_hidden!r}"
        )
        _end_any_active_session(acp_page)

    def test_state_teardown_on_stop(self, acp_page: Page) -> None:
        """stop() resets all five new U2 fields and sets terminalMode=null.

        Start an ACP session (populates terminalMode='acp-chat'), call
        stop() explicitly, then assert all new fields are back at defaults.
        """
        self._activate_session(acp_page, transport="acp")

        # Call stop() via Alpine data.
        acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return;
              try { window.Alpine.$data(root).stop(); } catch {}
            }"""
        )

        # Allow one tick for Alpine to settle.
        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return d && d.terminalMode === null;
              } catch { return false; }
            }""",
            timeout=3000,
        )

        state = acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return null;
              try {
                const d = window.Alpine.$data(root);
                return {
                  terminalMode: d.terminalMode,
                  acpMessagesLen: Array.isArray(d.acpMessages) ? d.acpMessages.length : -1,
                  streamingMessageId: d.streamingMessageId,
                  plan: d.plan,
                  pendingPermission: d.pendingPermission,
                };
              } catch { return null; }
            }"""
        )
        assert state is not None, "liveAgentConsole() Alpine data not accessible"
        assert state["terminalMode"] is None, f"terminalMode not reset: {state}"
        assert state["acpMessagesLen"] == 0, f"acpMessages not cleared: {state}"
        assert state["streamingMessageId"] is None, f"streamingMessageId not reset: {state}"
        assert state["plan"] is None, f"plan not reset: {state}"
        assert state["pendingPermission"] is None, f"pendingPermission not reset: {state}"
        _end_any_active_session(acp_page)

    def test_send_acp_input_pushes_user_message_in_chat_mode(self, acp_page: Page) -> None:
        """In ACP chat mode (_term is null), _sendAcpInput pushes a
        {role: 'user', text} entry into acpMessages instead of writing
        to xterm."""
        self._activate_session(acp_page, transport="acp")

        # Wait until connected so the WS is OPEN for _sendAcpInput.
        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try { return window.Alpine.$data(root).connected === true; }
              catch { return false; }
            }""",
            timeout=10000,
        )

        acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              const d = window.Alpine.$data(root);
              d.acpInput = 'hello-chat';
              d._sendAcpInput();
            }"""
        )

        # One message should have been pushed into acpMessages.
        acp_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              if (!root) return false;
              try {
                const d = window.Alpine.$data(root);
                return Array.isArray(d.acpMessages) && d.acpMessages.length >= 1;
              } catch { return false; }
            }""",
            timeout=5000,
        )

        messages = acp_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="liveAgentConsole()"]');
              try { return window.Alpine.$data(root).acpMessages; }
              catch { return []; }
            }"""
        )
        assert len(messages) >= 1, f"expected at least one message in acpMessages, got {messages!r}"
        user_msg = messages[0]
        assert user_msg.get("role") == "user", f"first message role mismatch: {user_msg!r}"
        assert user_msg.get("text") == "hello-chat", f"first message text mismatch: {user_msg!r}"
        _end_any_active_session(acp_page)
