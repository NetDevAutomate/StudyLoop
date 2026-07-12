"""Representative user-journey E2E — drives the REAL StudyLoop web UI.

This is the authoritative browser gate. It exercises the flow a real AuDHD
learner performs against the actual Alpine/HTMX UI (no fictional selectors):

  Phase 1  Body Double pomodoro (client-side timer)
  Phase 2  Study-session picker: real course data hydrates the vendor/course/
           agent selects; the 3-topic backlog surface is reachable
  Phase 3  Session start contract: POST /api/session/start returns a
           structured, correct response (201 for a real PTY agent, or a
           structured 5xx/4xx that the UI can render — never an opaque crash)

Phases that require a LIVE agent producing real Socratic output (mentor turns,
real generation review) cannot be asserted headless with a stub — a stub agent
does not speak the protocol or teach. Those are covered by
``test_socratic_steering.py`` (``live_provider`` marked, deselected by default)
and by the unit/integration suites for generation + review.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_representative_user_journey.py -m e2e
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

# Shared helpers live in the parent tests/ dir. Add it to sys.path inline
# (matching the precedent in test_active_session.py etc.) — a conftest.py here
# would collide with the parent tests/conftest.py module name.
_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18593
RESULTS = Path("test-results")


def _diag(page: Page | None, name: str) -> None:
    """Best-effort failure artifacts (screenshot + HTML)."""
    if page is None:
        return
    RESULTS.mkdir(exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{ts}.png"), full_page=True)
        (RESULTS / f"{name}-{ts}.html").write_text(page.content())
    except Exception:
        pass


@pytest.fixture(scope="module")
def running_server():
    """Real subprocess server (main thread owns the loop → SIGCHLD works)."""
    # Index real course content so the picker has data to hydrate.
    subprocess.run(
        ["uv", "run", "studyloop", "content", "index", "--force"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    proc = start_web_server(WEB_PORT)
    try:
        yield f"http://127.0.0.1:{WEB_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def _goto_view(page: Page, view: str) -> None:
    """Navigate via the real nav store (page.goto('#x') is ignored by design)."""
    page.evaluate("(v) => window.Alpine.store('nav').go(v)", view)
    page.wait_for_timeout(200)


def test_body_double_pomodoro_starts(browser, running_server: str) -> None:
    """Phase 1 — Body Double is a client-side pomodoro; timer initialises."""
    page = browser.new_page()
    try:
        page.goto(f"{running_server}/#body-double")
        page.wait_for_load_state("domcontentloaded")
        _goto_view(page, "body-double")
        focus = page.locator('.body-double-controls input[type="number"]').first
        focus.wait_for(state="visible", timeout=8000)
        focus.fill("5")
        page.locator('.body-double-controls button:has-text("Start Pomodoro")').click()
        timer = page.locator("#bd-timer-display")
        timer.wait_for(state="visible", timeout=8000)
        assert timer.inner_text().strip() != ""
    except Exception:
        _diag(page, "body_double")
        raise
    finally:
        page.close()


def test_study_picker_hydrates_real_course_data(browser, running_server: str) -> None:
    """Phase 2 — the study-session picker renders the real selects and
    hydrates vendor/course/agent options from /api/session/options."""
    page = browser.new_page()
    try:
        page.goto(f"{running_server}/#study-session")
        page.wait_for_load_state("domcontentloaded")
        _goto_view(page, "study-session")

        # The real picker selects (NOT a fictional select[name=provider]).
        for sel in ("#target-kind-select", "#agent-select", "#transport-select"):
            page.wait_for_selector(sel, state="attached", timeout=8000)

        # Options hydrate async from /api/session/options — wait for real data.
        page.wait_for_function(
            "() => document.querySelectorAll('#agent-select option').length > 1",
            timeout=10000,
        )
        agent_count = page.locator("#agent-select option").count()
        assert agent_count > 1, f"agent select not hydrated ({agent_count} options)"

        # Vendor path: switch target kind to vendor and confirm real vendors.
        page.select_option("#target-kind-select", "vendor")
        page.wait_for_function(
            "() => document.querySelectorAll('#vendor-select option').length > 1",
            timeout=10000,
        )
        assert page.locator("#vendor-select option").count() > 1

        # Start button exists (disabled until agent + topic — real UI contract).
        assert page.locator(".start-session-btn").count() == 1
    except Exception:
        _diag(page, "study_picker")
        raise
    finally:
        page.close()


def test_session_start_contract_is_structured(running_server: str) -> None:
    """Phase 3 — POST /api/session/start returns a STRUCTURED response.

    With no agent binary guaranteed in CI, a 503 with an ``install_hint`` is
    the correct, UI-renderable outcome (the frontend surfaces it). The one
    thing that must NOT happen is an opaque non-JSON 500. We assert the
    response is always JSON with a meaningful shape.
    """
    import requests

    resp = requests.post(
        f"{running_server}/api/session/start",
        json={"topic": "Abstraction and Coupling", "energy": 7, "transport": "pty"},
        timeout=15,
    )
    # Whatever the outcome, the body must be JSON (the frontend fix depends on
    # this — a non-JSON body is exactly the "Network error" masking bug).
    body = resp.json()
    assert isinstance(body, dict)
    if resp.status_code == 201:
        assert body["transport"] == "pty"
        assert body["ws_url"].startswith("/api/session/ws")
        # Clean up the started session so the module server stays usable.
        requests.post(f"{running_server}/api/session/end", timeout=10)
    else:
        # Structured failure: a cause the UI can render, not an opaque crash.
        assert resp.status_code in (400, 409, 500, 503)
        assert body.get("error") or body.get("install_hint") or body.get("repair")


def test_acp_transport_rejected_for_pty_only_agent(running_server: str) -> None:
    """Phase 3b — the server-side ACP guard rejects a PTY-only agent (400)."""
    import requests

    resp = requests.post(
        f"{running_server}/api/session/start",
        json={"topic": "X", "energy": 5, "agent": "claude", "transport": "acp"},
        timeout=15,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "claude" in body["error"]
    assert "ACP" in body["error"]


def test_backlog_surface_reachable(running_server: str) -> None:
    """Phase 2b — the 3-topic backlog contract is served."""
    import requests

    body = requests.get(f"{running_server}/api/backlog", timeout=10).json()
    assert "active" in body and "parking_lot" in body
    assert body["max_active"] >= 1


@pytest.mark.skip(
    reason="Requires a LIVE agent producing real Socratic mentor turns; a stub "
    "agent cannot speak the protocol or teach. Covered by "
    "test_socratic_steering.py (live_provider) + the mentor/persona unit tests."
)
def test_socratic_study_conversation(browser, running_server: str) -> None:  # pragma: no cover
    """Phase 4 (live-only) — mentor asks guiding questions, learner answers,
    DB updates. Deliberately skipped headless: see reason."""


# ---------------------------------------------------------------------------
# Fake-agent phases — the spawn → PTY → WS → terminal path, walkable in CI.
#
# These use a SEPARATE server (module-scoped fixture below) launched with
# STUDYLOOP_TEST_AGENT=1 so the deterministic 'fake' adapter registers. The
# main `running_server` stays vanilla so the picker-hydration tests keep
# asserting the real agent surface.
# ---------------------------------------------------------------------------

FAKE_WEB_PORT = 18594


@pytest.fixture(scope="module")
def fake_agent_server():
    """Server with the fake harness agent enabled (STUDYLOOP_TEST_AGENT=1)."""
    if not __import__("shutil").which("studyloop-fake-agent"):
        pytest.skip("studyloop-fake-agent not installed (editable install needed)")
    from _playwright_helpers import clean_ipc

    clean_ipc()  # stale IPC from earlier runs makes /session/end 404
    proc = start_web_server(FAKE_WEB_PORT, extra_env={"STUDYLOOP_TEST_AGENT": "1"})
    try:
        yield f"http://127.0.0.1:{FAKE_WEB_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_fake_agent_full_session_walk(fake_agent_server: str) -> None:
    """Spawn → 201+ws_url → WS bytes flow BOTH ways → end → DB row.

    The core product path that has broken twice before (SIGCHLD/uvicorn,
    un-endable sessions), previously untestable in CI because no real agent
    binary exists there. The fake agent makes the whole loop deterministic.
    """
    import json

    import requests
    from websockets.sync.client import connect as ws_connect

    # --- Spawn ---
    resp = requests.post(
        f"{fake_agent_server}/api/session/start",
        json={
            "topic": "Fake Agent Walk",
            "energy": 5,
            "agent": "fake",
            "transport": "pty",
        },
        timeout=20,
    )
    body = resp.json()
    assert resp.status_code == 201, f"spawn failed: {body}"
    assert body["transport"] == "pty"
    ws_url = f"ws://127.0.0.1:{FAKE_WEB_PORT}{body['ws_url']}"

    # --- WS: bytes out (banner), bytes in (input), echo back ---
    # The WS guard rejects requests with no Origin (non-browser clients);
    # send the same localhost Origin a browser would. NOTE the ordering:
    # /api/session/end must be called while the WS is still OPEN — a WS
    # disconnect triggers active.release() which clears the session state,
    # after which end returns 404 (that's the real product semantics; the
    # UI's End button posts while connected too).
    with ws_connect(
        ws_url,
        open_timeout=10,
        additional_headers={"Origin": fake_agent_server},
    ) as ws:
        buf = b""
        for _ in range(20):  # frames until the banner shows
            msg = ws.recv(timeout=10)
            if isinstance(msg, bytes):
                buf += msg
            if b"FAKE-AGENT READY" in buf:
                break
        assert b"FAKE-AGENT READY" in buf, f"no banner; got {buf!r}"

        ws.send(json.dumps({"type": "input", "data": "hello agent\r"}))
        buf = b""
        for _ in range(20):
            msg = ws.recv(timeout=10)
            if isinstance(msg, bytes):
                buf += msg
            if b"FAKE-AGENT SAYS:" in buf:
                break
        assert b"FAKE-AGENT SAYS:" in buf, f"no echo; got {buf!r}"

        # --- End WHILE connected (mirrors the UI's End button) ---
        end = requests.post(f"{fake_agent_server}/api/session/end", timeout=15)
        assert end.status_code == 200, end.text
        assert end.json()["ended"] is True

    # --- Phase 4: the ended session left a durable study_sessions row ---
    from studyloop.history.sessions import get_last_study_session

    last = get_last_study_session()
    assert last is not None, "no study_sessions row after session end"
    # Topics are normalised to lowercase on write.
    assert last["topic"].lower() == "fake agent walk"
    # started_at is always set; ended_at proves end_session_common ran.
    assert last["started_at"]


def test_fake_agent_terminal_renders_in_browser(browser, fake_agent_server: str) -> None:
    """Browser phase: start a session via the REAL UI and see agent bytes
    render in the xterm terminal — the full user-visible loop."""
    page = browser.new_page()
    try:
        # This test's subject is the terminal path, not the 3-topic rule —
        # stub the backlog empty so the park-first modal (tested elsewhere)
        # can't intercept the start when the REAL vault has 3 live topics.
        page.route(
            "**/api/backlog",
            lambda route: route.fulfill(
                json={
                    "active": [],
                    "parking_lot": [],
                    "active_count": 0,
                    "parking_lot_count": 0,
                    "max_active": 3,
                }
            ),
        )
        page.goto(f"{fake_agent_server}/#study-session")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)

        page.locator("#topic-input").fill("Browser Fake Walk")
        # Pick the fake agent explicitly (it's registered on this server).
        # Generous timeout: a cold server builds the picker's vault index on
        # the first /api/session/options call, which can take >5s.
        page.wait_for_function(
            """() => {
                const sel = document.querySelector('#agent-select');
                return sel && [...sel.options].some(o => o.value === 'fake');
            }""",
            timeout=30000,
        )
        page.select_option("#agent-select", value="fake")
        page.wait_for_function(
            "() => !document.querySelector('.start-session-btn').disabled",
            timeout=5000,
        )
        page.locator(".start-session-btn").click()

        # Proof the whole loop connected. xterm's WebGL renderer paints to a
        # canvas, so the banner text is NOT in the DOM — assert the two
        # DOM-visible signals instead: (1) the terminal header flips to
        # "Connected · fake" (WS established, transport Started), and (2) the
        # session status bar shows the live topic (state hydrated end-to-end).
        page.wait_for_function(
            """() => document.body.innerText.includes('Connected') &&
                     document.body.innerText.includes('fake')""",
            timeout=20000,
        )
        page.wait_for_function(
            "() => document.body.innerText.includes('Browser Fake Walk')",
            timeout=10000,
        )
        # And the byte-level banner IS asserted through the same WS pipeline
        # in test_fake_agent_full_session_walk — together the two tests cover
        # bytes AND pixels. Belt-and-braces: screenshot for human review.
        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / "fake-agent-terminal-connected.png"))
    except Exception:
        _diag(page, "fake-agent-browser")
        raise
    finally:
        try:
            import requests

            requests.post(f"{fake_agent_server}/api/session/end", timeout=10)
        except Exception:
            pass
        page.close()


@pytest.mark.skip(
    reason="Real content generation needs an LLM provider; deterministic "
    "generation is covered by test_content_generators_stub.py and the review "
    "flow by test_web_review_flow.py. A headless stub can't produce gradeable "
    "cards for a UI review walk."
)
def test_generate_and_review_flashcards_quizzes(browser, running_server: str) -> None:
    """Phase 5 (provider-only) — generate ≥5 cards/quizzes and review them."""
