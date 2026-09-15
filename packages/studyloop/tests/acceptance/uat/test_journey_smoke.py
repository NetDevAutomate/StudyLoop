"""UAT journey smoke test (deliverable 2 / TESTS FIRST): mechanics, CI-safe.

Proves the pieces this lane wires together actually COMPOSE, end to end,
with nothing requiring a real coding-harness binary, a real LLM, or
network access:

1. the hermetic server (``tests/_playwright_helpers.start_web_server``,
   E-B2), started with the repo's existing scripted ACP stub
   (``tests/_stub_acp_agent.py``) standing in for the mentor -- the same
   test hatch several ``test_web_acp_*`` e2e modules already use, never a
   real ``kiro-cli``;
2. a deterministic, versioned turn script (:mod:`acceptance.turn_script`,
   council D-16's ``scripted`` actor's own data shape) driven straight
   through the real web UI, mirroring the page-driving shape already
   proven in ``acceptance/test_kiro_web_acp_lane.py``;
3. B4's full evidence-bundle writer (:mod:`acceptance.uat.bundle`),
   capturing the resulting transcript into a run directory.

LEFT OUT, by name, not silently: wiring the acceptance tier's pluggable
``ScriptedActor``/``MentorTransport`` Protocol OBJECTS (rather than just
their turn-script DATA) through a live Playwright page turned out to
conflict with Playwright's sync API in this repo's environment --
Playwright's sync objects keep a greenlet-suspended asyncio event loop
"running" in the calling thread for the whole test, so
``asyncio.run(actor.converse(...))`` in the SAME thread raises
``RuntimeError: asyncio.run() cannot be called from a running event
loop``. Bridging the two cleanly needs cross-thread marshalling (the
actor's coroutine on one thread, Playwright's sync calls staying on the
thread that created them) that is out of scope for a smoke test whose
job is proving the hermetic-server + turn-script + bundle-writer
mechanics, not the actor Protocol's browser binding. A future lane can
either build that bridge or drive this journey through the async
Playwright API instead.

This is explicitly NOT a sign-off run: no rubric is graded, no council
seat is consulted, and the "mentor" here is a scripted stub, never the
real harness the brief's full journeys require (council D-16: the mentor
is never simulated in a LIVE acceptance test -- this smoke test is the
one named exception, same as the hermetic plumbing tests elsewhere in
this tier, and says so). Its only job is proving the WIRING, so a future
lane building the real pedagogy journeys on top of it starts from
mechanics that are already known to work.

Gated behind BOTH ``STUDYLOOP_ACC=1`` (inherited from
``tests/acceptance/conftest.py``) and ``STUDYLOOP_UAT=1`` (this
subpackage's own ``conftest.py``) -- council D-13's amendment that UAT
gets its own additional opt-in on top of acceptance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

# tests/acceptance/uat/test_journey_smoke.py -> tests/
_tests_dir = Path(__file__).resolve().parents[2]
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from _playwright_helpers import start_web_server  # noqa: E402

from acceptance.turn_script import load_turn_script  # noqa: E402
from acceptance.uat.bundle import ManifestFields, RunCounts, write_bundle  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, BrowserContext, Page

pytestmark = [pytest.mark.acceptance, pytest.mark.uat]

#: Distinct from every other fixed port the e2e/acceptance suites use.
WEB_PORT = 18620

SCRIPT = load_turn_script(
    {
        "version": 1,
        "turns": [
            {"prompt": "In one short sentence, what is a Python decorator?"},
            {"prompt": "Thanks. In one short sentence, what is a closure?"},
        ],
    }
)

#: Deterministic, canned mentor replies -- one per scripted learner turn, in
#: order. There is no LLM anywhere in this test; the stub agent below plays
#: them back verbatim, so the assertions can compare EXACT text, not shape.
_CANNED_REPLIES = (
    "A decorator wraps a function to add behaviour without editing it.",
    "A closure is a function that remembers variables from its enclosing scope.",
)


def _stub_acp_cmd() -> str:
    stub = _tests_dir / "_stub_acp_agent.py"
    return f'"{sys.executable}" "{stub}"'


def _chunk_update(text: str, session_id: str = "uat-smoke-session") -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


def _start_stub_server() -> object:
    extra_env = {
        "STUDYLOOP_TEST_ACP_CMD": _stub_acp_cmd(),
        "STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(
            [[_chunk_update(reply)] for reply in _CANNED_REPLIES]
        ),
        "STUB_ACP_PROMPT_STOP_REASON": "end_turn",
    }
    return start_web_server(WEB_PORT, extra_env=extra_env)


def _start_acp_session(page: Page) -> None:
    """Bypass-the-picker session start, mirroring the pattern already
    proven in ``test_web_acp_chat_ui.py``'s ``_activate_acp_session`` and
    ``acceptance/test_kiro_web_acp_lane.py``'s
    ``_start_acp_session_via_api``."""
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=8000)

    body = page.evaluate(
        """async () => {
          const res = await fetch('/api/session/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              topic: 'UAT smoke', energy: 5, agent: 'kiro', transport: 'acp',
            }),
          });
          return {status: res.status, body: await res.json()};
        }"""
    )
    assert body["status"] == 201, f"session/start failed: {body}"

    page.evaluate(
        """(data) => {
          const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
          if (timerRoot) {
            const d = window.Alpine.$data(timerRoot);
            d.sessionActive = true;
            d.topic = 'UAT smoke';
            d.startTime = new Date();
          }
          window.dispatchEvent(new CustomEvent('study-session-start', {
            detail: {
              topic: 'UAT smoke', energy: 5,
              sessionType: 'study', targetKind: 'topic', targetPath: null,
              agent: data.agent, resolvedAgent: data.agent,
              studySessionId: data.study_session_id,
              transport: data.transport, wsUrl: data.ws_url,
            },
          }));
        }""",
        body["body"],
    )
    page.wait_for_function(
        """() => {
          const root = document.querySelector('[x-data="liveAgentConsole()"]');
          if (!root) return false;
          try {
            const d = window.Alpine.$data(root);
            return d && d.connected === true && d.terminalMode === 'acp-chat';
          } catch { return false; }
        }""",
        timeout=15000,
    )


def _send_turn_and_get_reply(page: Page, prompt: str, *, prior_replies: int) -> str:
    """Send one scripted learner turn, wait for a NEW final reply, return its text.

    Mirrors ``acceptance/test_kiro_web_acp_lane.py``'s
    ``_send_turn_and_wait_for_reply``, extended to return the reply text so
    it can be asserted against the stub's exact canned text and recorded
    into the evidence bundle.
    """
    page.evaluate(
        """(text) => {
          const root = document.querySelector('[x-data="liveAgentConsole()"]');
          const d = window.Alpine.$data(root);
          d.acpInput = text;
          d._sendAcpInput();
        }""",
        prompt,
    )
    page.wait_for_function(
        """(priorReplies) => {
          const root = document.querySelector('[x-data="liveAgentConsole()"]');
          if (!root) return false;
          try {
            const d = window.Alpine.$data(root);
            const finals = d.acpMessages.filter(
              m => m.role === 'assistant' && m.status === 'final'
            );
            return finals.length > priorReplies;
          } catch { return false; }
        }""",
        arg=prior_replies,
        timeout=15000,
    )
    reply = page.evaluate(
        """() => {
          const root = document.querySelector('[x-data="liveAgentConsole()"]');
          const d = window.Alpine.$data(root);
          const finals = d.acpMessages.filter(
            m => m.role === 'assistant' && m.status === 'final'
          );
          return finals[finals.length - 1].text;
        }"""
    )
    assert isinstance(reply, str)
    return reply


def _end_session() -> None:
    import contextlib
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:{WEB_PORT}/api/session/end", method="POST")
    with contextlib.suppress(urllib.error.HTTPError, urllib.error.URLError):
        urllib.request.urlopen(req, timeout=10)


@pytest.fixture()
def _acp_context(browser: Browser) -> Generator[BrowserContext, None, None]:
    context = browser.new_context()
    try:
        yield context
    finally:
        context.close()


class TestJourneySmoke:
    def test_scripted_turns_complete_against_the_hermetic_server(
        self,
        tmp_path: Path,
        _acp_context: BrowserContext,
    ) -> None:
        proc = _start_stub_server()
        page = _acp_context.new_page()
        try:
            _start_acp_session(page)

            replies = [
                _send_turn_and_get_reply(page, turn.prompt, prior_replies=index)
                for index, turn in enumerate(SCRIPT.turns)
            ]

            assert replies == list(_CANNED_REPLIES)

            bundle_dir = tmp_path / "uat-smoke-run"
            transcript_bytes = json.dumps(
                [
                    {"learner": turn.prompt, "mentor": reply}
                    for turn, reply in zip(SCRIPT.turns, replies, strict=True)
                ],
                indent=2,
            ).encode("utf-8")
            fields = ManifestFields(
                run_id="uat-smoke-run",
                date="2026-09-15T00:00:00Z",
                repo_sha="mechanics-smoke-no-real-repo-sha",
                dirty=False,
                harness="kiro",
                actor_backend="scripted",
                platform=sys.platform,
                counts=RunCounts(passed=len(SCRIPT.turns), skipped=0, failed=0),
            )
            manifest_path = write_bundle(
                bundle_dir, fields, files={"transcript.json": transcript_bytes}
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["counts"]["passed"] == len(SCRIPT.turns)
            assert "transcript.json" in manifest["file_inventory"]
        finally:
            _end_session()
            proc.terminate()  # type: ignore[attr-defined]
            try:
                proc.wait(timeout=10)  # type: ignore[attr-defined]
            except Exception:
                proc.kill()  # type: ignore[attr-defined]
