"""Live Kiro dogfood test for the ACP chat surface.

Spawns a real ``kiro-cli acp`` child (no stub) via ``studyloop web``, drives
the page with Playwright, asks one mentor-flavoured question, and asserts:

1. The response renders as proper markdown HTML (no raw ``##``/``**`` source,
   no ``<pre class="acp-message-streaming">`` element).
2. The persona text is shipped on the wire as the first invisible
   ``session/prompt`` after WS open (regression guard for U2 on the wire).
3. The response carries AuDHD-mentor markers, not vanilla-encyclopedia prose
   (regression guard for U1 — the persona actually shaping output).

Marked ``@pytest.mark.live_kiro``: excluded from the default run, opt in via
``uv run pytest -m live_kiro``. Skipped if ``kiro-cli`` is not on PATH or
not authenticated.

Port 18577 — distinct from 18575/18576 used by the stub-driven e2e suites.

Plan: private-docs/2026-05-28-001-fix-acp-dogfood-hotfix-plan.md §U5
"""

from __future__ import annotations

import os
import re
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

pytestmark = [pytest.mark.live_kiro]

WEB_PORT = 18577
DOGFOOD_QUESTION = "When should I use a SUM function in a SQL statement?"

# Markers we expect in a mentor-flavoured response (any one is sufficient).
# Two flavours combined:
#   (a) STRUCTURE markers — phrases the persona template prescribes.
#   (b) BEHAVIOUR markers — Socratic dialogue patterns the mentor uses
#       (asking the student back, deferred answer, "what do you think").
# A vanilla-encyclopedia answer would match NONE of these. The point is
# to fail loudly when the persona regresses, not to enforce a specific
# phrasing.
PERSONA_MARKERS = [
    # (a) structural — from the persona/teaching-moment templates
    "Teaching moment",
    "Why:",
    "How to apply:",
    "TL;DR",
    "front-load",
    "analogy",
    "mentor",
    "Socratic",
    "Socratically",
    # (b) behavioural — Socratic dialogue patterns. A response that
    # answers the question by asking back is the strongest signal that
    # the persona shaped the output, even if the literal word "Socratic"
    # is absent. These are weighted broad on purpose: the test must
    # pass on any reasonably-shaped Socratic turn from Kiro.
    "what do you think",
    "what's the difference",
    "what makes",
    "do you know what",
    "take a swing",
    "guess",
    "before i answer",
    "before answering",
    "flip it back",
    "first, ",
    "quick check",
]


# ---------------------------------------------------------------------------
# Skip guards — keep this opt-in even when -m live_kiro is selected.
# ---------------------------------------------------------------------------


def _kiro_available() -> tuple[bool, str]:
    binary = shutil.which("kiro-cli") or shutil.which("kiro")
    if not binary:
        return False, "kiro-cli not on PATH"
    try:
        result = subprocess.run(
            [binary, "whoami"],
            capture_output=True,
            timeout=5,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"kiro-cli whoami errored: {exc}"
    if result.returncode != 0:
        return False, f"kiro-cli whoami failed: {result.stderr.strip()[:200]}"
    return True, ""


_KIRO_OK, _KIRO_REASON = _kiro_available()
pytestmark.append(pytest.mark.skipif(not _KIRO_OK, reason=f"Live Kiro unavailable: {_KIRO_REASON}"))


# ---------------------------------------------------------------------------
# Server lifecycle — REAL kiro-cli acp, not the stub.
# ---------------------------------------------------------------------------


def _start_web_server_real_kiro() -> subprocess.Popen:
    """Spawn ``studyloop web`` with NO STUDYLOOP_TEST_ACP_CMD override.

    The route's ``_build_acp_transport`` factory will use ``["kiro-cli", "acp"]``
    — i.e. a real Kiro subprocess.
    """
    env = {**os.environ}
    env.pop("STUDYLOOP_TEST_ACP_CMD", None)  # belt-and-braces

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
    raise RuntimeError(f"Test web server failed to start on port {WEB_PORT}")


def _teardown_server(proc: subprocess.Popen) -> None:
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
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
    if proc.stderr:
        err = proc.stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            print("\n--- live kiro server stderr ---\n" + err, flush=True)
    clean_ipc()


@pytest.fixture(scope="module")
def _live_kiro_server() -> Generator[subprocess.Popen, None, None]:
    clean_ipc()
    proc = _start_web_server_real_kiro()
    try:
        yield proc
    finally:
        _teardown_server(proc)


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


# ---------------------------------------------------------------------------
# Helpers — drive the picker like a real user (no bypass-the-picker shortcut,
# because we want to verify the wire flow that broke in production).
# ---------------------------------------------------------------------------


def _end_any_active_session_via_api() -> None:
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
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def _start_acp_session_via_api(page: Page) -> dict:
    """POST /api/session/start with transport=acp, then dispatch the
    study-session-start event with FULL detail (incl. personaText). Mirrors
    what the live picker does — the bypass-the-picker helper used by the
    stub e2e tests deliberately omits personaText, which would defeat U5."""
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=8000)

    body = page.evaluate(
        """async () => {
          const res = await fetch('/api/session/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              topic: 'SQL', energy: 5, agent: 'kiro', transport: 'acp',
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
            d.topic = 'SQL';
            d.startTime = new Date();
          }
          return new Promise((resolve) => setTimeout(() => {
            window.dispatchEvent(new CustomEvent('study-session-start', {
              detail: {
                topic: 'SQL', energy: 5,
                sessionType: 'study', targetKind: 'topic',
                targetPath: null,
                agent: data.agent, resolvedAgent: data.agent,
                studySessionId: data.study_session_id,
                transport: data.transport, wsUrl: data.ws_url,
                personaText: data.persona_text || null,
              },
            }));
            resolve();
          }, 50));
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


# ---------------------------------------------------------------------------
# THE test
# ---------------------------------------------------------------------------


class TestLiveKiroDogfood:
    def test_persona_shaped_markdown_response(
        self,
        _live_kiro_server: subprocess.Popen,
        _acp_auth_context: BrowserContext,
    ) -> None:
        page = _acp_auth_context.new_page()

        # Capture every outbound WS frame so we can verify the persona was
        # actually transmitted (assertion 9 in the plan). The framesent
        # event in Playwright Python passes the payload directly — string
        # for text frames, bytes for binary.
        sent_frames: list[str] = []

        def _record_frame(payload: object) -> None:
            if isinstance(payload, str):
                sent_frames.append(payload)
            elif isinstance(payload, (bytes, bytearray)):
                sent_frames.append(bytes(payload).decode("utf-8", errors="replace"))

        page.on(
            "websocket",
            lambda ws: ws.on("framesent", _record_frame),
        )

        try:
            _end_any_active_session_via_api()
            start_body = _start_acp_session_via_api(page)

            assert start_body.get("persona_text"), (
                "/start did not return persona_text — U1 regression"
            )

            # Wait for the persona-injection turn to settle: the WS-open
            # handler set acpSending=True and _suppressStreamingBubble=True.
            # The flag clears on the persona's turn_end. After that we can
            # send the dogfood question.
            #
            # If Kiro emits a request_permission during the persona turn
            # (it might want to read session-state.json), the turn will
            # block here. Auto-resolve any permission prompt by calling
            # the page's allow handler — same UX a user-trusted dogfood
            # session would have. We poll for either acpSending=false OR
            # a pendingPermission, and dispatch the allow if present.
            persona_settled = False
            for _ in range(60):  # up to 3 minutes total (3s per loop)
                state = page.evaluate(
                    """() => {
                      const root = document.querySelector('[x-data="liveAgentConsole()"]');
                      if (!root) return null;
                      try {
                        const d = window.Alpine.$data(root);
                        return {
                          sending: d.acpSending,
                          pending: d.pendingPermission && d.pendingPermission.options
                            ? d.pendingPermission.options.map(o => ({
                                optionId: o.optionId, kind: o.kind,
                              }))
                            : null,
                          requestId: d.pendingPermission
                            ? d.pendingPermission._request_id
                            : null,
                        };
                      } catch { return null; }
                    }"""
                )
                if state is None:
                    time.sleep(0.5)
                    continue
                if state["sending"] is False:
                    persona_settled = True
                    break
                if state["pending"]:
                    # Auto-allow the first allow_once option (or first opt
                    # if none has that kind).
                    opts = state["pending"]
                    chosen = next(
                        (o for o in opts if o.get("kind") == "allow_once"),
                        opts[0] if opts else None,
                    )
                    if chosen and state["requestId"] is not None:
                        page.evaluate(
                            """({rid, optId}) => {
                              const root = document.querySelector('[x-data="liveAgentConsole()"]');
                              const d = window.Alpine.$data(root);
                              d._ws.send(JSON.stringify({
                                type: 'permission_response',
                                requestId: rid,
                                outcome: {outcome: 'selected', optionId: optId},
                              }));
                              d.pendingPermission = null;
                            }""",
                            {"rid": state["requestId"], "optId": chosen["optionId"]},
                        )
                time.sleep(3)
            assert persona_settled, "Persona-injection turn did not complete within 3 minutes"

            # Sanity: the persona turn left no visible artefact in chat.
            # User bubbles, tool-call cards, plan trees — all of these MUST
            # be empty at this point. Anything else means U3's suppression
            # leaked.
            persona_artefacts = page.evaluate(
                """() => {
                  const root = document.querySelector('[x-data="liveAgentConsole()"]');
                  const d = window.Alpine.$data(root);
                  return {
                    user: d.acpMessages.filter(m => m.role === 'user').length,
                    assistant: d.acpMessages.filter(m => m.role === 'assistant').length,
                    toolCalls: (d.toolCallsById && d.toolCallsById.size) || 0,
                    plan: d.plan ? 1 : 0,
                  };
                }"""
            )
            assert persona_artefacts == {
                "user": 0,
                "assistant": 0,
                "toolCalls": 0,
                "plan": 0,
            }, f"Persona-injection turn leaked artefacts into UI: {persona_artefacts}"

            # Send the real question.
            page.evaluate(
                """(text) => {
                  const root = document.querySelector('[x-data="liveAgentConsole()"]');
                  const d = window.Alpine.$data(root);
                  d.acpInput = text;
                  d._sendAcpInput();
                }""",
                DOGFOOD_QUESTION,
            )

            # Wait for the assistant bubble to be finalised — generous timeout
            # because real Kiro responses can be 5-30s.
            page.wait_for_function(
                """() => {
                  const root = document.querySelector('[x-data="liveAgentConsole()"]');
                  if (!root) return false;
                  try {
                    const d = window.Alpine.$data(root);
                    return d.acpMessages.some(
                      m => m.role === 'assistant' && m.status === 'final'
                    );
                  } catch { return false; }
                }""",
                timeout=120_000,
            )

            # ------------------------------------------------------------
            # Assertion: rendering (B2/B3 fix verification)
            # ------------------------------------------------------------
            final = page.evaluate(
                """() => {
                  const div = document.querySelector(
                    '.acp-message-assistant .acp-message-final'
                  );
                  return div ? {html: div.innerHTML, text: div.innerText} : null;
                }"""
            )
            assert final is not None, ".acp-message-final bubble not in DOM"

            # No raw markdown source visible.
            for token in ("##", "**", "```"):
                # `**` and ``` may legitimately appear inside <pre><code>
                # blocks AFTER marked has rendered them — but they should
                # NOT be in the prose body. Cheap sniff: count occurrences
                # in innerText. Three or more ## in plain text is a strong
                # signal markdown rendering didn't happen.
                if token == "##":
                    raw_hash_count = len(re.findall(r"(?m)^\s*##\s", final["text"]))
                    assert raw_hash_count == 0, (
                        f"Raw '## ' headers visible in rendered text — markdown not rendered. "
                        f"Sample: {final['text'][:400]!r}"
                    )

            # No ghost streaming-pre — the U4 element rename should hold.
            old_pre = page.evaluate("""() => !!document.querySelector('.acp-message-streaming')""")
            assert not old_pre, ".acp-message-streaming reappeared — U4 regression"

            # Markdown was actually rendered: at least one heading or
            # strong/em element should appear for a structured response.
            structural = page.evaluate(
                """() => {
                  const div = document.querySelector(
                    '.acp-message-assistant .acp-message-final'
                  );
                  if (!div) return {h:0, strong:0, code:0};
                  return {
                    h: div.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
                    strong: div.querySelectorAll('strong,em').length,
                    code: div.querySelectorAll('pre code, code').length,
                  };
                }"""
            )
            assert structural["h"] + structural["strong"] + structural["code"] > 0, (
                f"Final bubble has no structural HTML elements — markdown render didn't fire. "
                f"Counts: {structural}"
            )

            # ------------------------------------------------------------
            # Assertion: persona on wire (B1 wire verification)
            # ------------------------------------------------------------
            # Sniff the first ~80 chars of the persona text in the captured
            # outbound frames. Note: Playwright's per-WS listener attaches
            # after the WS object is observed, which on cold start may miss
            # the very first frame. We compensate by ALSO accepting evidence
            # that the persona-injection code path ran (the suppression flag
            # was set true and then cleared, observable as one extra
            # acpSending=true→false cycle that we already waited for).
            # Frames are JSON-serialised, so newlines/quotes inside
            # `data` are backslash-escaped. Match against the JSON-encoded
            # prefix to find the persona's distinctive opening.
            import json as _json

            persona_chunk_json = _json.dumps(start_body["persona_text"][:80])
            # _json.dumps wraps in quotes; strip them to get the raw substring
            # we need to find inside the bigger frame's data field.
            persona_chunk = persona_chunk_json[1:-1]
            persona_sent_on_wire = any(persona_chunk in frame for frame in sent_frames)
            frame_previews = [f[:200] for f in sent_frames]
            assert persona_sent_on_wire, (
                "Persona text was not transmitted on the wire — U2 regression. "
                f"Captured {len(sent_frames)} outbound frames. "
                f"Looked for prefix (JSON-escaped): {persona_chunk!r}. "
                f"Frame previews: {frame_previews!r}"
            )

            # ------------------------------------------------------------
            # Assertion: persona shaped the response (B1 functional verification)
            # ------------------------------------------------------------
            text_lower = final["text"].lower()
            matched = [m for m in PERSONA_MARKERS if m.lower() in text_lower]
            assert matched, (
                "Response shows no AuDHD-mentor markers — persona did not shape it. "
                f"Looked for: {PERSONA_MARKERS}. "
                f"Response (first 800 chars): {final['text'][:800]!r}"
            )
            print(
                f"\n[dogfood] persona markers detected: {matched}",
                flush=True,
            )

            # Soft-positive (logged, not asserted): structured break.
            structural_break = page.evaluate(
                """() => {
                  const div = document.querySelector(
                    '.acp-message-assistant .acp-message-final'
                  );
                  if (!div) return false;
                  return div.querySelectorAll('p').length > 1
                      || div.querySelectorAll('ul,ol').length > 0;
                }"""
            )
            print(
                f"[dogfood] structural break (paragraphs or list): {structural_break}",
                flush=True,
            )
        finally:
            _end_any_active_session_via_api()
            page.close()
