"""First real acceptance lane (deliverable 5): Kiro via the web ACP path.

``STUDYLOOP_ACC=1`` + ``kiro-cli`` present -> start a real ``studyloop web``
against a SCRATCH env (never the developer's real ``~/.config/studyloop``,
council D-11), drive one real ACP session with a SCRIPTED learner (D-16
scoping -- deterministic turns, no LLM on the learner side; the mentor,
kiro-cli, is never mocked in a live acceptance test), and assert the
lifecycle completed: session start returns a persona, the assistant answers
each scripted turn, and the session ends cleanly with no crash.

Reuses the repo's existing hermetic server helper
(``tests/_playwright_helpers.start_web_server``, E-B2) rather than forking a
new subprocess-spawning path, and follows the page-driving shape already
proven in ``test_web_acp_dogfood_kiro.py`` — trading that file's persona-marker
and markdown-rendering assertions (a DIFFERENT regression this lane is not
about) for the scratch-isolation and scripted-turn concerns that ARE this
lane's job.

LEFT OUT (see lanes.json B1 receipt / left_out): DB-row-level validators over
the session-memory schema (topic/struggle rows, ``session_search`` ID-set
membership, a written wind-down record) are not implemented here — that
schema belongs to the session-memory subsystem this lane does not own, and
wiring it in is squarely B2 (harness matrix, DB-backed evidence) / B4 (the
UAT bundle writer)'s job. This lane proves the MECHANICS: real kiro-cli,
real scratch isolation, a real ACP lifecycle, never executed against the
owner's real config.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = Path(__file__).resolve().parent.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from _playwright_helpers import effective_credentials, start_web_server  # noqa: E402

from acceptance.turn_script import load_turn_script  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, BrowserContext, Page

    from acceptance.isolation import ScratchEnv

pytestmark = [pytest.mark.acceptance]

WEB_PORT = 18599  # distinct from every fixed port the e2e/live suites use

SCRIPT = load_turn_script(
    {
        "version": 1,
        "turns": [
            {"prompt": "In one short sentence, what is a Python decorator?"},
            {"prompt": "Thanks. In one short sentence, what is a closure?"},
        ],
    }
)


def _kiro_available() -> tuple[bool, str]:
    """Named-skip predicate (D-13): report WHICH binary/step is missing."""
    binary = shutil.which("kiro-cli") or shutil.which("kiro")
    if not binary:
        return False, "kiro-cli not on PATH"
    try:
        result = subprocess.run([binary, "whoami"], capture_output=True, timeout=5, text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"kiro-cli whoami errored: {exc}"
    if result.returncode != 0:
        return False, f"kiro-cli whoami failed: {result.stderr.strip()[:200]}"
    return True, ""


def _end_session(port: int) -> None:
    import base64
    import contextlib
    import urllib.error
    import urllib.request

    user, password = effective_credentials()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/session/end", method="POST")
    if password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    # Already ended / nothing active is not this helper's job to assert.
    with contextlib.suppress(urllib.error.HTTPError):
        urllib.request.urlopen(req, timeout=10)


def _start_acp_session_via_api(page: Page, port: int) -> dict:
    """Start a real ACP (kiro) session the way the live picker does.

    Mirrors ``test_web_acp_dogfood_kiro.py``'s helper of the same name: the
    bypass-the-picker shortcut some stub-driven e2e tests use deliberately
    omits ``personaText``, which would defeat this lane's whole point
    (a real persona through a real, isolated mentor process).
    """
    page.goto(f"http://127.0.0.1:{port}/#study-session")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=8000)

    body = page.evaluate(
        """async (port) => {
          const res = await fetch(`http://127.0.0.1:${port}/api/session/start`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              topic: 'Acceptance Lane', energy: 5, agent: 'kiro', transport: 'acp',
            }),
          });
          return {status: res.status, body: await res.json()};
        }""",
        port,
    )
    assert body["status"] == 201, f"session/start failed: {body}"

    page.evaluate(
        """(data) => {
          const timerRoot = document.querySelector('[x-data="sessionTimer()"]');
          if (timerRoot) {
            const d = window.Alpine.$data(timerRoot);
            d.sessionActive = true;
            d.topic = 'Acceptance Lane';
            d.startTime = new Date();
          }
          window.dispatchEvent(new CustomEvent('study-session-start', {
            detail: {
              topic: 'Acceptance Lane', energy: 5,
              sessionType: 'study', targetKind: 'topic', targetPath: null,
              agent: data.agent, resolvedAgent: data.agent,
              studySessionId: data.study_session_id,
              transport: data.transport, wsUrl: data.ws_url,
              personaText: data.persona_text || null,
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
    return body["body"]


def _send_turn_and_wait_for_reply(page: Page, prompt: str, *, prior_replies: int) -> None:
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
        timeout=90_000,
    )


@pytest.fixture()
def _acp_auth_context(browser: Browser) -> Generator[BrowserContext, None, None]:
    user, password = effective_credentials()
    ctx_args: dict = {}
    if password:
        ctx_args["http_credentials"] = {"username": user, "password": password}
    context = browser.new_context(**ctx_args)
    try:
        yield context
    finally:
        context.close()


class TestKiroWebAcpLane:
    def test_scripted_learner_completes_a_full_lifecycle(
        self,
        scratch_env: ScratchEnv,
        _acp_auth_context: BrowserContext,
    ) -> None:
        ok, reason = _kiro_available()
        if not ok:
            pytest.skip(f"Live Kiro unavailable: {reason}")

        proc = start_web_server(WEB_PORT, env=scratch_env.env)
        page = _acp_auth_context.new_page()
        try:
            start_body = _start_acp_session_via_api(page, WEB_PORT)
            assert start_body.get("persona_text"), (
                "/session/start did not return persona_text -- no persona shipped"
            )

            for replies_so_far, turn in enumerate(SCRIPT.turns):
                _send_turn_and_wait_for_reply(page, turn.prompt, prior_replies=replies_so_far)
                time.sleep(0.5)  # let the turn settle before the next send

            final_count = page.evaluate(
                """() => {
                  const root = document.querySelector('[x-data="liveAgentConsole()"]');
                  const d = window.Alpine.$data(root);
                  return d.acpMessages.filter(
                    m => m.role === 'assistant' && m.status === 'final'
                  ).length;
                }"""
            )
            assert final_count == len(SCRIPT.turns), (
                f"expected {len(SCRIPT.turns)} final assistant replies, got {final_count}"
            )
        finally:
            _end_session(WEB_PORT)
            page.close()
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)

    def test_named_skip_when_kiro_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(f) mechanics-layer proof of the skip path, independent of this
        machine's actual kiro-cli install -- the live test above always
        demonstrates the SAME predicate; this test proves the predicate
        itself names the binary rather than failing or hanging."""
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        ok, reason = _kiro_available()
        assert ok is False
        assert "kiro-cli" in reason
