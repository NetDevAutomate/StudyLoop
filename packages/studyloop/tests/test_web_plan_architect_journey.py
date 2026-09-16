"""Browser journey: "Plan with architect" from the Plans view (#14, design §5, T5.1).

One click on the Plans view starts a *planning* session — ``POST
/api/session/start`` with ``purpose: "planning"`` and the learner's subject (or
``""``, which the server resolves to the fixed label ``Study plan``) — and hands
the learner to the **existing** Study Session console, labelled as a planning
session. Nothing is created by the launch: the study-plan architect creates the
plan through the plan tools during the interview (D-11).

Real browser, real server, fake agent: the fixtures are the shared Playwright
helpers (``_playwright_helpers``, the same ``start_web_server`` +
``STUDYLOOP_TEST_AGENT_CMD`` seam ``test_web_agent_matrix.py`` uses), so the
PTY child is ``echo agent-stub-ready; exec cat`` and no vendor binary or paid
call is involved. The fake agent also copies the persona file it was handed
into a directory this test owns, which is how the brief's *structure* is
checked — never its wording.

Marked ``e2e`` like every other browser module here, so it is deselected by
the default run: ``just e2e packages/studyloop/tests/test_web_plan_architect_journey.py``.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

# Sibling-module import: tests/ has no __init__.py.
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    clean_ipc,
    effective_credentials,
    start_web_server,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import BrowserContext, Page, Route

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

# Unique fixed port — enforced by tests/test_port_uniqueness.py; 18611 is the
# developer's live server.
WEB_PORT = 18626
BASE = f"http://127.0.0.1:{WEB_PORT}"

#: The persona section headings whose *presence and order* the journey asserts
#: (structure, not wording). ``## Planning brief`` is the section
#: ``build_canonical_persona`` renders for ``brief=``; the three ``###`` are
#: ``_render_planning_brief``'s parts; ``## Tooling`` opens the architect
#: persona's MCP-before-CLI section (T4.2).
BRIEF_STRUCTURE = (
    "## Planning brief",
    "### Interview",
    "### Evidence from the learner's history",
    "### Existing plans",
    "## Tooling",
)


# ---------------------------------------------------------------------------
# Fixtures — one server per module, hermetic, with a fake agent that leaks the
# persona file into a directory the test owns
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> Generator[dict[str, Path], None, None]:
    """Directories this module owns: the plans dir (so "no plan was created" is
    a fact about the click), the session dir (so the persona file the PTY
    adapter writes can be read back), and the drop box the fake agent copies
    its persona file into."""
    root = Path(tempfile.mkdtemp(prefix="studyloop-architect-journey-"))
    dirs = {
        "plans": root / "study-plans",
        "sessions": root / "session-dir",
        "personas": root / "personas-seen",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    try:
        yield dirs
    finally:
        # ``mkdtemp`` is not ``tmp_path``: nothing removes it for us. Thirty-nine
        # of these were found in $TMPDIR while closing #15 (review 5, GPT F13).
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def web_server(world: dict[str, Path]):
    clean_ipc()
    # ``{persona_file}`` is substituted by the PTY transport factory
    # (_transport.py: ``test_cmd.format(persona_file=...)``). The copy is the
    # journey's window onto what the architect was actually handed.
    agent_cmd = (
        f'cp "{{persona_file}}" "{world["personas"]}/$(date +%s%N).md"; '
        "echo agent-stub-ready; exec cat"
    )
    proc = start_web_server(
        WEB_PORT,
        extra_env={
            "STUDYLOOP_TEST_AGENT_CMD": agent_cmd,
            "STUDYLOOP_PLANS_DIR": str(world["plans"]),
            "STUDYLOOP_SESSION_DIR": str(world["sessions"]),
            # The web app warms the semantic query encoder on a background
            # thread at boot (lane A1). In this isolated HOME there is no
            # model, so the warm constructs one from scratch (torch import,
            # "Creating a new one with mean pooling") and holds the GIL long
            # enough that one POST /api/session/start in this module misses
            # its 20 s cap when the machine is busy — reproduced 5/5 module
            # runs at load ≈ 7.5 (a different test each time, always the
            # start POST), 3/3 green with the warm off. Nothing here searches
            # sessions, so the lexical mode is the honest isolation, not a
            # shortcut: the journey under test is the plan door, not retrieval.
            "STUDYLOOP_RETRIEVAL_MODE": "lexical",
        },
    )
    try:
        yield proc
    finally:
        _end_session_over_http()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
        clean_ipc()


auth_context = auth_context_fixture_factory()


@pytest.fixture()
def page(web_server, auth_context: BrowserContext) -> Generator[Page, None, None]:
    _ = web_server
    page = auth_context.new_page()
    try:
        yield page
    finally:
        # Every test leaves the slot free for the next one.
        _end_any_active_session(page)
        page.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _end_session_over_http() -> None:
    user, password = effective_credentials()
    req = urllib.request.Request(f"{BASE}/api/session/end", method="POST")
    if password:
        import base64

        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with contextlib.suppress(Exception):
        urllib.request.urlopen(req, timeout=3)


def _end_any_active_session(page: Page) -> None:
    try:
        if not page.url.startswith(BASE):
            page.goto(f"{BASE}/")
            page.wait_for_load_state("domcontentloaded")
        page.evaluate(
            "async () => { try { await fetch('/api/session/end', {method: 'POST'}); } catch {} }"
        )
        page.wait_for_timeout(150)
    except Exception:
        pass


def _goto_plans(page: Page) -> None:
    # A hash-only goto on an already-loaded page is a same-document navigation
    # (the nav store reads the hash at init only), so load the root, then
    # switch views through the store exactly as the sidebar button does.
    page.goto(f"{BASE}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    # The plans store's OWN completion flag, not a proxy signal.
    page.wait_for_function(
        "() => window.Alpine.store('plans') && window.Alpine.store('plans').initDone === true",
        timeout=8000,
    )
    page.locator('[data-testid="plan-new"]').wait_for(state="visible", timeout=8000)


def _instrument_starts(page: Page) -> None:
    """Count what the page does on a launch: ``study-session-start`` events
    (one per launch is the contract) and WebSocket constructions."""
    page.evaluate(
        """() => {
          window.__architectProbe = { startEvents: 0, purposes: [], sockets: [] };
          window.addEventListener('study-session-start', (e) => {
            window.__architectProbe.startEvents += 1;
            window.__architectProbe.purposes.push((e.detail && e.detail.purpose) || null);
          });
          const RealWebSocket = window.WebSocket;
          window.WebSocket = function (url, ...rest) {
            window.__architectProbe.sockets.push(String(url));
            return new RealWebSocket(url, ...rest);
          };
          window.WebSocket.prototype = RealWebSocket.prototype;
          window.WebSocket.OPEN = RealWebSocket.OPEN;
          window.WebSocket.CLOSED = RealWebSocket.CLOSED;
          window.WebSocket.CONNECTING = RealWebSocket.CONNECTING;
          window.WebSocket.CLOSING = RealWebSocket.CLOSING;
        }"""
    )


def _probe(page: Page) -> dict:
    return page.evaluate("() => window.__architectProbe")


def _wait_for_console(page: Page) -> None:
    """The existing Study Session console, mounted for a PTY session."""
    page.wait_for_function("() => window.location.hash === '#study-session'", timeout=10000)
    page.wait_for_function(
        """() => {
          const selector = '.agent-console[x-data="liveAgentConsole()"]';
          const roots = [...document.querySelectorAll(selector)];
          return roots.some((el) => {
            const d = window.Alpine.$data(el);
            return d && d.terminalMode === 'xterm' && d.connected === true;
          });
        }""",
        timeout=20000,
    )


def _visible_purpose_labels(page: Page) -> list[str]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="console-purpose-label"]')]
             .filter((el) => el.offsetParent !== null
                             && window.getComputedStyle(el).display !== 'none')
             .map((el) => el.textContent.trim())"""
    )


def _session_state(page: Page) -> dict:
    return page.evaluate(
        "async () => (await fetch('/api/session/state', {cache: 'no-store'})).json()"
    )


def _plans(page: Page) -> dict:
    return page.evaluate("async () => (await fetch('/api/plans')).json()")


def _click_plan_with_architect(page: Page, subject: str = "") -> dict:
    """Click once; return the one start request/response pair the click made."""
    posts: list[dict] = []

    def _on_response(response) -> None:  # type: ignore[no-untyped-def]
        request = response.request
        if request.method == "POST" and request.url.endswith("/api/session/start"):
            posts.append(
                {
                    "body": json.loads(request.post_data or "{}"),
                    "status": response.status,
                    "response": response.json() if response.status != 204 else {},
                }
            )

    page.on("response", _on_response)
    if subject:
        page.locator('[data-testid="plan-architect-subject"]').fill(subject)
    button = page.get_by_role("button", name="Plan with architect")

    def _is_start(response) -> bool:  # type: ignore[no-untyped-def]
        return response.request.method == "POST" and response.url.endswith("/api/session/start")

    with page.expect_response(_is_start, timeout=20000):
        button.click()
    page.wait_for_function(
        "() => window.location.hash === '#study-session'"
        " || !!document.querySelector('.picker-error')",
        timeout=10000,
    )
    # A second POST, if the click ever made one, would land in this window.
    page.wait_for_timeout(600)
    page.remove_listener("response", _on_response)
    assert len(posts) == 1, f"expected exactly one POST /api/session/start, saw {posts}"
    return posts[0]


# ---------------------------------------------------------------------------
# T5.1 — the journey
# ---------------------------------------------------------------------------


def test_plan_with_architect_action_posts_purpose_planning_and_navigates_to_console(
    page: Page,
) -> None:
    """One click → one POST with ``purpose: "planning"`` and the learner's
    subject → 201 → the existing Study Session console (``#study-session``)."""
    _goto_plans(page)
    _instrument_starts(page)

    post = _click_plan_with_architect(page, subject="SQL window functions")

    assert post["status"] == 201, post
    assert post["body"]["purpose"] == "planning"
    assert post["body"]["topic"] == "SQL window functions"
    assert post["body"]["origin"] == "study", "the Study Session console owns this session"
    assert post["response"]["purpose"] == "planning"
    assert post["response"]["topic"] == "SQL window functions"
    assert post["response"]["ws_url"].startswith("/api/session/ws?study_session_id=")
    _wait_for_console(page)
    assert _probe(page)["startEvents"] == 1
    assert _probe(page)["purposes"] == ["planning"]


def test_plan_with_architect_without_a_subject_lets_the_server_name_it_study_plan(
    page: Page,
) -> None:
    """``topic`` is sent as ``""`` (never omitted — the model requires it); the
    server, not the UI, resolves it to the fixed label."""
    _goto_plans(page)

    post = _click_plan_with_architect(page)

    assert post["status"] == 201, post
    assert post["body"]["topic"] == ""
    assert post["response"]["topic"] == "Study plan"
    _wait_for_console(page)


def test_console_is_labelled_planning_and_label_survives_reconnect(page: Page) -> None:
    """The console carries a purpose label read from the 201 body; the state
    endpoint persists ``purpose`` (D-11); a reload re-adopts the live session
    from ``GET /api/session/state`` and the label is rendered again."""
    _goto_plans(page)
    _click_plan_with_architect(page)
    _wait_for_console(page)

    labels = _visible_purpose_labels(page)
    assert len(labels) == 1, labels
    assert "planning" in labels[0].lower(), labels

    state = _session_state(page)
    assert state["purpose"] == "planning"
    assert state["study_session_id"]

    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    _wait_for_console(page)
    labels_after = _visible_purpose_labels(page)
    assert len(labels_after) == 1, labels_after
    assert "planning" in labels_after[0].lower(), labels_after


def test_brief_structure_present_not_wording(page: Page, world: dict[str, Path]) -> None:
    """The persona the architect was handed has the planning brief as its own
    section with the three parts in order, ahead of the architect body whose
    tooling section prefers the MCP tools — structure only; no interview
    question or persona sentence is asserted."""
    seen_before = set(world["personas"].iterdir())
    _goto_plans(page)
    _click_plan_with_architect(page)
    _wait_for_console(page)

    new_files = sorted(set(world["personas"].iterdir()) - seen_before)
    assert len(new_files) == 1, f"the fake agent should have received one persona: {new_files}"
    persona = new_files[0].read_text(encoding="utf-8")

    positions = [persona.find(heading) for heading in BRIEF_STRUCTURE]
    assert all(p >= 0 for p in positions), dict(zip(BRIEF_STRUCTURE, positions, strict=True))
    assert positions == sorted(positions), "the brief's parts are out of order"
    assert "**Mode:** plan-architect" in persona
    assert "Resuming Previous Session" not in persona, "a fresh interview is not a resumption"


def test_manual_new_plan_form_still_works(page: Page) -> None:
    """The existing create path is untouched by the new control: New plan →
    form → Create plan → the reader shows the plan and the API lists it."""
    _goto_plans(page)
    before = _plans(page)["count"]

    page.locator('[data-testid="plan-new"]').click()
    page.locator('[data-testid="plan-create-form"]').wait_for(state="visible", timeout=8000)
    page.locator('[data-testid="plan-field-title"]').fill("Manual plan still works")
    page.locator('[data-testid="plan-field-why"]').fill(
        "Because the button beside it must not break it."
    )
    page.locator('[data-testid="plan-field-success"]').fill("Create a plan without the architect")
    page.locator('[data-testid="plan-field-topics"]').fill("sql")
    page.locator('[data-testid="plan-field-milestones"]').fill(
        "Read the OVER clause (concepts: window function)"
    )
    page.locator('[data-testid="plan-create-submit"]').click()
    page.locator('[data-testid="plan-detail"]').wait_for(state="visible", timeout=12000)

    assert (
        "Manual plan still works" in page.locator('[data-testid="plan-detail-title"]').inner_text()
    )
    assert _plans(page)["count"] == before + 1
    # No session was started by the manual path.
    assert not _session_state(page).get("study_session_id")


def test_one_console_one_websocket(page: Page) -> None:
    """Exactly one addressed launch: one ``study-session-start`` event, one
    WebSocket to the session's ``ws_url``, one visible console — the Plans
    view mounted no terminal of its own."""
    _goto_plans(page)
    _instrument_starts(page)

    post = _click_plan_with_architect(page)
    _wait_for_console(page)

    probe = _probe(page)
    assert probe["startEvents"] == 1, probe
    ws_urls = [u for u in probe["sockets"] if "/api/session/ws" in u]
    assert len(ws_urls) == 1, probe
    assert post["response"]["ws_url"] in ws_urls[0]

    visible_consoles = page.evaluate(
        """() => [...document.querySelectorAll('.agent-console')]
             .filter((el) => el.offsetParent !== null).length"""
    )
    assert visible_consoles == 1
    # The Plans view keeps no live listener of its own for the console's event.
    plans_view_terminals = page.evaluate(
        "() => document.querySelectorAll("
        "'.plans-panel .xterm-mount, .plans-panel .agent-console').length"
    )
    assert plans_view_terminals == 0


def test_conflict_returns_structured_error_and_offers_reattach(page: Page) -> None:
    """A second launch while a session is active is the existing conflict shape
    on the wire (409: ``error``, ``study_session_id``, ``topic``, ``agent``,
    ``detached``, ``reattach_url``) and, in the UI, the existing recovery block
    with the reattach lever — not a dead end and not a second console."""
    _goto_plans(page)
    first = _click_plan_with_architect(page)
    assert first["status"] == 201
    _wait_for_console(page)

    # On the wire: the server refuses the second start with the structured 409.
    second = page.evaluate(
        """async () => {
          const res = await fetch('/api/session/start', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({topic: '', energy: 5, agent: 'claude', transport: 'pty',
                                  purpose: 'planning', origin: 'study'}),
          });
          return {status: res.status, body: await res.json()};
        }"""
    )
    assert second["status"] == 409, second
    body = second["body"]
    assert set(body) >= {"error", "study_session_id", "topic", "agent", "detached", "reattach_url"}
    assert body["study_session_id"] == first["response"]["study_session_id"]
    assert body["reattach_url"] == first["response"]["ws_url"]

    # In the UI: a Plans-view launch that meets that 409 lands the learner on
    # the picker's recovery block with the reattach lever, not a bare error.
    _end_any_active_session(page)
    _goto_plans(page)
    conflict = dict(body)

    def _refuse(route: Route) -> None:
        if route.request.method == "POST":
            route.fulfill(status=409, content_type="application/json", body=json.dumps(conflict))
        else:
            route.continue_()

    page.route("**/api/session/start", _refuse)
    page.get_by_role("button", name="Plan with architect").click()
    page.locator(".picker-error").wait_for(state="visible", timeout=10000)
    assert body["error"] in page.locator(".picker-error").inner_text()
    page.locator("#study-conflict-reattach").wait_for(state="visible", timeout=5000)
    assert (
        page.evaluate(
            "() => document.querySelectorAll('.agent-console .xterm-mount .xterm').length"
        )
        == 0
    )


def test_starting_the_architect_creates_no_plan(page: Page, world: dict[str, Path]) -> None:
    """D-11: the launch creates nothing — the plan list is unchanged and the
    plans directory is untouched until the interview creates a plan."""
    _goto_plans(page)
    plans_before = _plans(page)
    files_before = sorted(p.name for p in world["plans"].glob("*.md"))

    post = _click_plan_with_architect(page)
    assert post["status"] == 201
    _wait_for_console(page)

    assert _plans(page) == plans_before
    assert sorted(p.name for p in world["plans"].glob("*.md")) == files_before
    state = _session_state(page)
    assert "plan_id" not in state, "no plan id is stored on the session (D-11)"
