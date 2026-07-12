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
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

from _playwright_helpers import start_web_server

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


@pytest.mark.skip(
    reason="Real content generation needs an LLM provider; deterministic "
    "generation is covered by test_content_generators_stub.py and the review "
    "flow by test_web_review_flow.py. A headless stub can't produce gradeable "
    "cards for a UI review walk."
)
def test_generate_and_review_flashcards_quizzes(browser, running_server: str) -> None:
    """Phase 5 (provider-only) — generate ≥5 cards/quizzes and review them."""
