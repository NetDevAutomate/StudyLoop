"""End-to-end Body Double journey — drives the REAL StudyLoop web UI.

This is the authoritative gate for Body Double as a first-class surface. It
walks the whole workflow a learner actually performs, against the real Alpine
components and the real server — no stubbed selectors, no mocked fetches:

  Phase 1  Body doubling is its OWN surface — the Study Session picker no longer
           offers it as a "session type", and the Body Double view owns a
           picker, a focus card and a capture panel of its own
  Phase 2  The focus contract (rule of 3) is visible and enforced: a 4th topic
           goes to the parking lot, never into a 4th live slot
  Phase 3  A real session starts HERE — real agent spawn, real WebSocket — and
           only THIS surface's console mounts (the Study Session console must
           not cross-fire)
  Phase 4  The agent asks a question RELEVANT to what is being studied, the
           learner answers, and the agent grades the answer
  Phase 5  Notes are written as STRUCTURED Markdown (server-supplied per-kind
           template, plus a mermaid diagram) and the preview renders it fully
  Phase 6  Tangents are PARKED into the same board the Parking Lot panel shows
  Phase 7  Both are REVIEWABLE in side panels: notes render full Markdown
           (headings, table, task list, code, diagram), and the agent-facing
           export groups them intent-first
  Phase 8  Both are SELECTIVELY DELETABLE — one, a chosen subset, all — soft,
           with undo
  Phase 9  Everything survives a reload (it is in the DB, not in the DOM)

Each run gets its own temp config with its own ``session_db`` and its own IPC
directory, so the suite never touches the developer's real notes, parked topics
or live session.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_body_double_journey.py -m e2e
"""

from __future__ import annotations

import contextlib
import socket
import sys
import urllib.request
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

STUDY_TOPIC = "Python Decorators"

#: The note a learner would actually write during a body-double stretch: prose,
#: structure, a table, a task list, code and a diagram. Every block type here is
#: asserted in the render phase, so "structured Markdown" is a claim this suite
#: can cash rather than a description.
STRUCTURED_NOTE = """## What I worked out

A decorator is just `f = decorator(f)` with nicer syntax.

> The wrapper runs first; the original function runs when the wrapper calls it.

### Evidence

| Step | Observation |
| --- | --- |
| `@timed` applied | `wrapper` replaces `func` |
| call site | wrapper body runs before `func` |

- [x] Traced the call order by hand
- [ ] Re-check with `functools.wraps` removed

```python
import functools

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
```

```mermaid
flowchart LR
    call["caller"] --> wrapper["wrapper()"]
    wrapper --> inner["original function"]
```
"""

PLAN_NOTE = """## Goal

- Explain decorators without notes open

## Steps

1. Re-derive `f = decorator(f)`
2. Write one from scratch
3. Break `functools.wraps` and read the fallout
"""

PARK_NOTE = """## Why it matters

Class-based decorators come up in the framework code I have to read next.

- [ ] Compare `__call__` against a closure

```mermaid
graph TD
    A["@decorator"] --> B["__call__"]
    A --> C["closure"]
```
"""


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def bd_env(tmp_path_factory: pytest.TempPathFactory) -> Generator[RunningServer, None, None]:
    """A server in its own world, with the deterministic harness agent.

    Module-scoped because a server start is expensive and every phase below is
    read/write against the same isolated DB — which is also what makes the
    journey a journey rather than nine unrelated tests.
    """
    root = tmp_path_factory.mktemp("body-double-journey")
    world = build_test_world(root, _free_port(), fake_agent=True)
    server = start_server(world)
    try:
        yield server
    finally:
        # End any live session before the server goes away, so a failed phase
        # cannot leave an orphaned agent process behind.
        with contextlib.suppress(Exception):
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{server.base_url}/api/session/end", data=b"", method="POST"
                ),
                timeout=10,
            )
        server.stop()


@pytest.fixture(scope="module")
def page(bd_env, browser):
    """One page for the whole journey — state carries forward, as it would."""
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

    def _record(msg) -> None:
        # Location matters: a bare "Event" (which is what Chrome logs for a
        # dropped WebSocket) is unactionable without knowing where it came from.
        if msg.type != "error":
            return
        where = ""
        try:
            loc = msg.location or {}
            where = f" @ {loc.get('url', '?')}:{loc.get('lineNumber', '?')}"
        except Exception:
            where = ""
        errors.append(f"console.error: {msg.text}{where}")

    pg.on("console", _record)

    # Every API call the UI makes, as (METHOD, path). This is how the phases
    # below assert that a button hits the documented endpoint rather than
    # something else — "the export button works" is a weaker claim than "the
    # export button issues GET /api/notes/markdown against the real server".
    calls: list[tuple[str, str]] = []

    def _record_request(request) -> None:
        path = urlsplit(request.url).path
        if path.startswith("/api/"):
            calls.append((request.method, path))

    pg.on("request", _record_request)

    pg._studyloop_errors = errors
    pg._studyloop_api_calls = calls
    yield pg
    with contextlib.suppress(Exception):
        pg.evaluate("async () => { await fetch('/api/session/end', {method: 'POST'}); }")
    context.close()


def _assert_called(page: Page, method: str, path: str) -> None:
    """Assert the UI issued ``method path`` against the real server."""
    calls = getattr(page, "_studyloop_api_calls", [])
    assert (method, path) in calls, (
        f"the UI never issued {method} {path}; recent API calls: {calls[-12:]}"
    )


# ---------------------------------------------------------------------------
# Helpers — these ARE the representative user actions
# ---------------------------------------------------------------------------


def _open_body_double(page: Page, server: RunningServer) -> None:
    """Switch to the Body Double view.

    Uses the nav store rather than a second ``goto`` with a different hash: a
    same-document hash change does not re-run page load, so navigating that way
    from another view silently leaves the old view mounted.
    """
    if not page.url.startswith(server.base_url):
        page.goto(f"{server.base_url}/#body-double")
    page.wait_for_function("() => !!window.Alpine", timeout=15_000)
    page.evaluate("() => window.Alpine.store('nav').go('body-double')")
    page.wait_for_selector(".body-double-view", state="visible", timeout=15_000)


def _diag(page: Page, label: str) -> None:
    """Screenshot + HTML on demand — a headless failure with no artifact is
    unactionable."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        page.screenshot(path=str(RESULTS / f"body-double-{label}.png"), full_page=True)
    with contextlib.suppress(Exception):
        (RESULTS / f"body-double-{label}.html").write_text(page.content(), encoding="utf-8")


def _api(page: Page, path: str) -> dict:
    """Read an API endpoint through the page (same origin, same auth)."""
    return page.evaluate("async (p) => { const r = await fetch(p); return await r.json(); }", path)


def _write_note(page: Page, *, kind: str, title: str, body: str, confidence: int = 0) -> None:
    """Fill and submit the note composer the way a learner would."""
    page.locator("#bd-tab-note").click()
    page.wait_for_selector("#bd-note-form", state="visible", timeout=5_000)
    page.select_option("#bd-note-kind", value=kind)
    page.locator("#bd-note-title").fill(title)
    page.locator("#bd-note-body").fill(body)
    if confidence:
        page.locator(".bd-confidence select").select_option(value=str(confidence))
    page.locator("#bd-save-note").click()
    page.wait_for_selector("#bd-note-saved", state="visible", timeout=10_000)


def _park(page: Page, question: str, notes: str = "") -> None:
    page.locator("#bd-tab-park").click()
    page.wait_for_selector("#bd-park-form", state="visible", timeout=5_000)
    page.locator("#bd-park-question").fill(question)
    if notes:
        page.locator("#bd-park-notes").fill(notes)
    page.locator("#bd-park-submit").click()
    page.wait_for_selector("#bd-park-saved", state="visible", timeout=10_000)


def _open_notes_panel(page: Page) -> None:
    if not page.locator("#notes-panel").is_visible():
        opener = page.locator("#bd-open-notes")
        if opener.is_visible():
            page.locator("#bd-open-notes").click()
        else:
            page.locator("#notes-toggle").click()
    page.wait_for_selector("#notes-panel", state="visible", timeout=10_000)


#: Read the Body Double terminal's scrollback.
#:
#: xterm.js paints to a canvas/WebGL surface, so terminal output is NOT in
#: ``innerText`` — asserting on the DOM would silently never match. The buffer
#: is reached through the live Alpine component instance, which is also the only
#: place the (deliberately non-reactive) ``_term`` handle exists.
_TERMINAL_TEXT_JS = """
() => {
  const el = document.querySelector('.bd-console-panel .session-terminal-area');
  if (!el || !window.Alpine) return '';
  const data = window.Alpine.$data(el);
  const term = data && data._term;
  if (!term || !term.buffer) return '';
  const buf = term.buffer.active;
  const lines = [];
  for (let i = 0; i < buf.length; i += 1) {
    const line = buf.getLine(i);
    if (line) lines.push(line.translateToString(true));
  }
  return lines.join('\\n');
}
"""


def _terminal_text(page: Page) -> str:
    return page.evaluate(_TERMINAL_TEXT_JS)


def _wait_for_terminal_text(page: Page, needle: str, timeout: int = 60_000) -> None:
    page.wait_for_function(
        "(needle) => { const read = " + _TERMINAL_TEXT_JS + "; return read().includes(needle); }",
        arg=needle,
        timeout=timeout,
    )


def _open_parking_panel(page: Page) -> None:
    if not page.locator("#parking-panel").is_visible():
        page.locator("#parking-lot-toggle").click()
    page.wait_for_selector("#parking-panel", state="visible", timeout=10_000)


def _ensure_topic_live(page: Page, topic: str) -> None:
    """Guarantee ``topic`` occupies a focus slot, parking it if it does not.

    The phases below tell one story in order, but a developer debugging the
    session phase should not have to run the four before it. This makes the
    precondition explicit and idempotent instead of implicit in test ordering.
    """
    slot = page.locator(f'.bd-focus-slot-topic:has-text("{topic}")')
    if slot.count() == 0:
        _park(page, topic)
        page.wait_for_selector(
            f'.bd-focus-slot-topic:has-text("{topic}")', state="visible", timeout=15_000
        )


# ---------------------------------------------------------------------------
# Phase 1 — Body doubling is its own surface
# ---------------------------------------------------------------------------


def test_phase1_body_double_owns_its_surface(page: Page, bd_env: RunningServer) -> None:
    """The Study Session picker no longer offers Body Double as a session type,
    and the Body Double view has a picker, a focus card and a capture panel."""
    try:
        page.goto(f"{bd_env.base_url}/#study-session")
        page.wait_for_function("() => !!window.Alpine", timeout=15_000)
        # #topic-input, not .session-start-picker: the Body Double view now has
        # a picker of its own, so the class is no longer unique.
        page.wait_for_selector("#topic-input", state="visible", timeout=15_000)

        # The dead dropdown value is gone from the markup AND from the API.
        assert page.locator("#session-type-select").count() == 0, (
            "Study Session still offers a Session Type dropdown"
        )
        options = _api(page, "/api/session/options")
        assert {entry["value"] for entry in options["session_types"]} == {"study"}

        _open_body_double(page, bd_env)
        assert page.locator(".body-double-view .body-double-header h2").inner_text() == (
            "Body Double"
        )
        for selector in ("#bd-focus", "#bd-activity-input", "#bd-start-session", "#bd-capture"):
            assert page.locator(selector).is_visible(), f"{selector} missing on Body Double"

        # The retained Pomodoro affordances (three suites address these).
        assert page.locator(
            '.body-double-view .body-double-controls input[type="number"]'
        ).first.is_visible()
        assert page.locator(
            '.body-double-view .body-double-controls button:has-text("Start Pomodoro")'
        ).is_visible()

        # The dead ttyd panel is gone: it was gated on an event only the retired
        # transport fired, so it rendered as permanently blank space.
        assert page.locator(".body-double-view .terminal-panel").count() == 0
    except Exception:
        _diag(page, "phase1")
        raise


# ---------------------------------------------------------------------------
# Phase 2 — the rule of 3
# ---------------------------------------------------------------------------


def test_phase2_focus_contract_caps_live_topics_at_three(page: Page, bd_env: RunningServer) -> None:
    """A 4th topic goes to the parking lot; the panel says so, and the server agrees."""
    try:
        _open_body_double(page, bd_env)
        assert page.locator("#bd-focus-count").inner_text() == "0 of 3 topics"
        assert page.locator("#bd-focus-empty").is_visible()

        # Order matters and is part of the contract: the live slots are the
        # MOST RECENT pending topics, so the first thing parked is the first
        # thing to fall out of focus. STUDY_TOPIC is parked last precisely so
        # the later phases can work on it.
        for topic in ("Spark shuffle", "SQL window functions", "dbt tests", STUDY_TOPIC):
            _park(page, topic)

        page.wait_for_function(
            "() => document.querySelector('#bd-focus-count').innerText === '3 of 3 topics'",
            timeout=15_000,
        )
        assert page.locator("#bd-focus-at-capacity").is_visible(), (
            "at-capacity badge should show once three topics are live"
        )
        assert page.locator("#bd-focus .bd-focus-slot").count() == 3

        # The overflow is parked, not lost, and the panel points at the board.
        # Waited for, not asserted instantly: the focus card re-reads the server
        # after each park, so the 4th park's refresh is in flight.
        page.wait_for_selector("#bd-focus-parked", state="visible", timeout=15_000)
        focus = _api(page, "/api/body-double/focus")
        live = [slot["topic"] for slot in focus["slots"]]
        assert STUDY_TOPIC in live, f"most recent topic should be live, got {live}"
        assert "Spark shuffle" not in live, (
            f"oldest topic should have fallen out of focus, got {live}"
        )
        assert focus["max_active"] == 3
        assert focus["at_capacity"] is True
        assert len(focus["slots"]) == 3
        assert focus["parking_lot_count"] == 1
    except Exception:
        _diag(page, "phase2")
        raise


# ---------------------------------------------------------------------------
# Phase 3 + 4 — a real session, and a relevant question
# ---------------------------------------------------------------------------


def test_phase3_session_starts_on_this_surface_only(page: Page, bd_env: RunningServer) -> None:
    """Real spawn, real WebSocket, and only the Body Double console mounts."""
    try:
        _open_body_double(page, bd_env)
        _ensure_topic_live(page, STUDY_TOPIC)

        # Pick the topic straight off the focus card — the whole point of the
        # card is that it is actionable, not decorative.
        page.locator(f'.bd-focus-slot-topic:has-text("{STUDY_TOPIC}")').first.click()
        assert page.locator("#bd-activity-input").input_value() == STUDY_TOPIC

        page.wait_for_function(
            """() => {
                const sel = document.querySelector('#bd-agent-select');
                return sel && [...sel.options].some((o) => o.value === 'codex');
            }""",
            timeout=60_000,
        )
        page.select_option("#bd-agent-select", value="codex")
        page.locator("[data-testid='bd-energy-slider']").press("ArrowRight")
        page.wait_for_function(
            "() => !document.querySelector('#bd-start-session').disabled", timeout=10_000
        )
        page.locator("#bd-start-session").click()

        # The live strip appears on THIS surface.
        page.wait_for_selector("#bd-live-activity", state="visible", timeout=60_000)
        assert page.locator("#bd-live-activity").inner_text() == STUDY_TOPIC

        # The console mounts here...
        page.wait_for_selector(".bd-console-panel .xterm-mount", state="visible", timeout=60_000)
        # ...and NOT on the Study Session surface. Both consoles are live in the
        # DOM from page load (x-data under x-show is not lazy), so an unaddressed
        # start event would mount two xterms on one PTY.
        study_terminals = page.evaluate(
            """() => {
                const area = document.querySelector(
                    '.session-active-layout .session-terminal-area');
                if (!area) return 0;
                return area.querySelectorAll('.xterm-screen, canvas').length;
            }"""
        )
        assert study_terminals == 0, "the Study Session console cross-fired on a Body Double start"

        # The server recorded which surface owns the session, so a refresh can
        # reattach the console to the right place.
        state = _api(page, "/api/session/state")
        assert state["origin"] == "body-double"
    except Exception:
        _diag(page, "phase3")
        raise


def test_phase4_agent_asks_a_relevant_question_and_grades_the_answer(
    page: Page, bd_env: RunningServer
) -> None:
    """Presence is not enough: the body double must engage with the topic."""
    try:
        _wait_for_terminal_text(page, "FAKE-AGENT ASKS")
        transcript = _terminal_text(page)
        # Relevance is checkable, not a vibe: the question must be about the
        # topic the session was started on.
        assert "decorator" in transcript.lower(), (
            f"agent question was not relevant to {STUDY_TOPIC!r}: {transcript[-600:]!r}"
        )

        # Answer it the way a learner does — typing into the terminal.
        page.locator(".bd-console-panel .xterm-mount").click()
        page.keyboard.type("a callable that wraps a function and returns a new one")
        page.keyboard.press("Enter")
        _wait_for_terminal_text(page, "FAKE-AGENT VERDICT", timeout=45_000)
    except Exception:
        _diag(page, "phase4")
        raise


# ---------------------------------------------------------------------------
# Phase 5 — structured Markdown notes
# ---------------------------------------------------------------------------


def test_phase5_notes_are_structured_markdown_and_preview_renders(
    page: Page, bd_env: RunningServer
) -> None:
    """The composer scaffolds structure from the server, and the preview shows
    the real render pipeline — not a plain-text approximation."""
    try:
        _open_body_double(page, bd_env)
        page.locator("#bd-tab-note").click()
        page.wait_for_selector("#bd-note-form", state="visible", timeout=5_000)

        # The per-kind template comes from the SERVER, so the shape an agent
        # expects to parse and the shape the learner is nudged into cannot drift.
        page.select_option("#bd-note-kind", value="plan")
        page.locator("#bd-note-template").click()
        plan_template = page.locator("#bd-note-body").input_value()
        assert "## Goal" in plan_template and "## Steps" in plan_template, (
            f"plan template not applied: {plan_template!r}"
        )

        page.select_option("#bd-note-kind", value="assessment")
        page.locator("#bd-note-template").click()
        assert "unaided" in page.locator("#bd-note-body").input_value().lower()

        # Now write the real note, with a diagram inserted by the button.
        page.select_option("#bd-note-kind", value="note")
        page.locator("#bd-note-title").fill("Decorator call order")
        page.locator("#bd-note-body").fill(STRUCTURED_NOTE)
        page.locator("#bd-note-preview-toggle").click()
        page.wait_for_selector("#bd-note-preview", state="visible", timeout=5_000)

        preview = page.locator("#bd-note-preview")
        page.wait_for_function(
            "() => document.querySelector('#bd-note-preview svg') !== null",
            timeout=15_000,
        )
        # Every structural block must actually render.
        assert preview.locator("h2").count() >= 1, "heading did not render"
        assert preview.locator("table").count() == 1, "GFM table did not render"
        assert preview.locator("blockquote").count() == 1, "blockquote did not render"
        assert preview.locator('input[type="checkbox"]').count() == 2, "task list did not render"
        assert preview.locator("pre code").count() >= 1, "code fence did not render"
        assert preview.locator("svg").count() == 1, "mermaid diagram did not render"

        page.select_option("[data-testid='bd-note-confidence']", value="3")
        page.locator("#bd-save-note").click()
        page.wait_for_selector("#bd-note-saved", state="visible", timeout=10_000)

        # A second note of a different kind, so the export has something to group.
        _write_note(
            page, kind="plan", title="Plan: own the decorator story", body=PLAN_NOTE, confidence=2
        )

        notes = _api(page, "/api/notes")
        assert notes["active_total"] == 2
        by_title = {n["title"]: n for n in notes["notes"]}
        stored = by_title["Decorator call order"]
        assert stored["kind"] == "note"
        assert stored["confidence"] == 3
        assert stored["topic"] == STUDY_TOPIC, (
            f"note was not attributed to the focus topic: {stored['topic']!r}"
        )
        # Stored as clean Markdown — the durability contract.
        assert "\r" not in stored["body"]
        assert "```mermaid" in stored["body"]
        assert by_title["Plan: own the decorator story"]["kind"] == "plan"
    except Exception:
        _diag(page, "phase5")
        raise


# ---------------------------------------------------------------------------
# Phase 6 — parked tangents land on the shared board
# ---------------------------------------------------------------------------


def test_phase6_parked_tangent_lands_on_the_parking_board(
    page: Page, bd_env: RunningServer
) -> None:
    """Park from Body Double; review it on the Parking Lot board, Markdown intact."""
    try:
        _open_body_double(page, bd_env)
        _park(page, "Class-based decorators — worth it?", PARK_NOTE)

        _open_parking_panel(page)
        card = page.locator('#parking-panel .parking-card:has-text("Class-based decorators")').first
        card.wait_for(state="visible", timeout=10_000)
        # The server derives has_diagram, so the collapsed card advertises the
        # diagram without the client re-parsing the body. is_visible(), not
        # count(): the chip is always in the DOM, x-show only toggles display.
        assert card.locator(".parking-chip.diagram").is_visible(), (
            "parked note with a mermaid fence did not get the diagram chip"
        )

        # Open it: the Markdown body survived the trip, and renders.
        #
        # Scoped to THIS card, not by id: every card keeps its own editor in the
        # DOM (x-show toggles display, it does not unmount), so the editor's id
        # resolves once per card. Class selectors under the card are unambiguous.
        card.locator(".parking-card-title").click()
        note_input = card.locator(".parking-note-input")
        note_input.wait_for(state="visible", timeout=10_000)
        assert "## Why it matters" in note_input.input_value()

        card_id = card.get_attribute("data-id")
        card.locator('button:has-text("Preview")').first.click()
        preview = card.locator(".parking-note-preview")
        preview.wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            """(id) => {
                const c = document.querySelector(
                    '#parking-panel .parking-card[data-id="' + id + '"]');
                const p = c && c.querySelector('.parking-note-preview');
                return !!p && !!p.querySelector('svg');
            }""",
            arg=card_id,
            timeout=15_000,
        )
        assert preview.locator('input[type="checkbox"]').count() == 1
        card.locator(".parking-card-title").click()  # collapse again
    except Exception:
        _diag(page, "phase6")
        raise


# ---------------------------------------------------------------------------
# Phase 7 — review both in the side panels
# ---------------------------------------------------------------------------


def test_phase7_notes_panel_renders_and_exports(page: Page, bd_env: RunningServer) -> None:
    """The notes panel is a READING surface, and the export is what an agent reads."""
    try:
        _open_notes_panel(page)
        assert page.locator("#notes-total-count").inner_text() == "2 notes"

        # Opening the notes panel must close the parking lot — they share the
        # grid column, and two asides in one cell means the loser renders at
        # zero width with nothing to explain why.
        assert not page.locator("#parking-panel").is_visible()
        assert "notes-open" in page.evaluate(
            "() => document.querySelector('.app-layout').className"
        )

        card = page.locator('#notes-panel .note-card:has-text("Decorator call order")').first
        assert card.locator(".note-card-meta .parking-chip").first.inner_text() == "Note"
        assert "3/5" in card.locator(".note-card-meta").inner_text()
        assert card.locator(".note-card-preview").inner_text().strip(), (
            "collapsed card shows no preview — the list is unrecognisable"
        )

        card.locator(".note-card-title").click()
        # Scoped to THIS card: every card keeps its own reading surface in the
        # DOM, so an unscoped `.note-rendered` hits the first hidden one.
        note_id = card.get_attribute("data-id")
        rendered = card.locator(".note-rendered")
        rendered.wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            """(id) => {
                const c = document.querySelector(
                    '#notes-panel .note-card[data-id="' + id + '"]');
                const r = c && c.querySelector('.note-rendered');
                return !!r && !!r.querySelector('svg');
            }""",
            arg=note_id,
            timeout=15_000,
        )
        assert rendered.locator("table").count() == 1
        assert rendered.locator('input[type="checkbox"]').count() == 2
        assert rendered.locator("pre code").count() >= 1
        assert rendered.locator("svg").count() == 1
        assert rendered.locator("blockquote").count() == 1

        # The kind filter narrows the list rather than pretending to.
        page.select_option("#notes-kind-filter", value="plan")
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '1 note'",
            timeout=10_000,
        )
        assert page.locator("#notes-panel .note-card").count() == 1
        page.select_option("#notes-kind-filter", value="")
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '2 notes'",
            timeout=10_000,
        )

        # The agent-facing export: intent (plan) before raw material (notes),
        # and a valid heading tree so depth-based parsing works.
        page.locator("#notes-export-toggle").click()
        page.wait_for_selector("#notes-export-source", state="visible", timeout=10_000)
        # The export the learner reads is the SAME document the agent reads —
        # served by the endpoint, not re-derived in the browser.
        _assert_called(page, "GET", "/api/notes/markdown")
        export = page.locator("#notes-export-source").inner_text()
        assert export.startswith("# Study notes")
        assert "## Study plan" in export
        assert "## Notes" in export
        assert export.index("## Study plan") < export.index("## Notes")
        # A body heading nests UNDER its note title rather than jumping above it.
        assert "#### What I worked out" in export, (
            f"body headings were not demoted under the note title: {export[:600]!r}"
        )
    except Exception:
        _diag(page, "phase7")
        raise


def test_phase7b_a_note_can_be_edited_in_place(page: Page, bd_env: RunningServer) -> None:
    """Review is only useful if a terse capture can be grown into a real note."""
    try:
        _open_notes_panel(page)
        card = page.locator(
            '#notes-panel .note-card:has-text("Plan: own the decorator story")'
        ).first
        card.locator(".note-card-title").click()
        card.locator('.note-editor-tabs button:has-text("Edit")').click()
        body = card.locator(".note-edit-body")
        body.wait_for(state="visible", timeout=5_000)
        # Trailing whitespace and CRLF-ish sloppiness the server must clean up.
        body.fill(PLAN_NOTE + "\n\n4. Teach it back   \n\n\n")
        card.locator('.note-edit-actions button:has-text("+ Diagram")').click()
        card.locator(".note-save-btn").click()
        page.wait_for_function(
            """(id) => {
                const c = document.querySelector(
                    '#notes-panel .note-card[data-id="' + id + '"]');
                const b = c && c.querySelector('.note-save-btn');
                return !!b && !b.innerText.includes('Saving');
            }""",
            arg=card.get_attribute("data-id"),
            timeout=10_000,
        )

        # The editor adopts the SERVER's normalised body: what is durable is what
        # was stored, and showing the typed version would quietly disagree with
        # the next reload.
        saved = body.input_value()
        assert "Teach it back" in saved
        assert "   \n" not in saved, f"trailing whitespace survived: {saved!r}"
        assert "\n\n\n" not in saved
        assert "```mermaid" in saved
    except Exception:
        _diag(page, "phase7b")
        raise


# ---------------------------------------------------------------------------
# Phase 8 — selective deletion, soft, with undo
# ---------------------------------------------------------------------------


def test_phase8_notes_delete_one_subset_and_all_with_undo(
    page: Page, bd_env: RunningServer
) -> None:
    try:
        _open_notes_panel(page)
        # Give ourselves enough notes to delete a genuine SUBSET.
        page.locator("#bd-open-notes")  # keep the panel toggle addressable
        _open_body_double(page, bd_env)
        _write_note(
            page,
            kind="question",
            title="Open: descriptor protocol?",
            body="## What I don't understand yet\n\n- how `__get__` binds\n",
        )
        _write_note(
            page,
            kind="win",
            title="Win: wrote one from scratch",
            body="## What clicked\n\n- closures\n",
        )
        _open_notes_panel(page)
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '4 notes'",
            timeout=10_000,
        )

        # --- delete ONE ---
        page.locator(
            '#notes-panel .note-card:has-text("Win: wrote one from scratch") .note-card-delete'
        ).click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '3 notes'",
            timeout=10_000,
        )
        assert page.locator("#notes-undo-clear").is_visible()
        # The delete button hits the documented endpoint against the real
        # server — not a different path, and not an in-process shortcut.
        _assert_called(page, "POST", "/api/notes/clear")
        # Soft: the row is still there, which is what makes undo possible.
        assert len(_api(page, "/api/notes?status=all")["notes"]) == 4
        page.locator("#notes-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '4 notes'",
            timeout=10_000,
        )
        _assert_called(page, "POST", "/api/notes/restore")

        # --- delete a USER-CHOSEN SUBSET ---
        page.locator("#notes-select-mode").click()
        page.locator("#notes-clear-selected").wait_for(state="visible", timeout=5_000)
        assert page.locator("#notes-clear-selected").is_disabled(), (
            "clear-selected must be disabled until something is actually selected"
        )
        page.locator(
            '#notes-panel .note-card:has-text("Open: descriptor protocol?") .note-card-check'
        ).check()
        page.locator(
            '#notes-panel .note-card:has-text("Win: wrote one from scratch") .note-card-check'
        ).check()
        assert page.locator("#notes-selected-count").inner_text() == "2 selected"
        page.locator("#notes-clear-selected").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '2 notes'",
            timeout=10_000,
        )
        remaining = {n["title"] for n in _api(page, "/api/notes")["notes"]}
        assert remaining == {"Decorator call order", "Plan: own the decorator story"}, (
            f"the wrong subset was deleted: {remaining}"
        )
        page.locator("#notes-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '4 notes'",
            timeout=10_000,
        )

        # --- delete ALL, then undo ---
        page.locator("#notes-clear-all").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '0 notes'",
            timeout=10_000,
        )
        assert page.locator("#notes-empty").is_visible()
        page.locator("#notes-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '4 notes'",
            timeout=10_000,
        )
    except Exception:
        _diag(page, "phase8")
        raise


def test_phase8b_parked_topics_delete_selectively_with_undo(
    page: Page, bd_env: RunningServer
) -> None:
    """The same clearing vocabulary on the other panel — one, a subset, all, undo."""
    try:
        _open_parking_panel(page)
        before = _api(page, "/api/parking/board")["total"]
        assert before >= 3, f"expected several parked items by now, got {before}"

        # --- one ---
        page.locator(
            '#parking-panel .parking-card:has-text("Class-based decorators") .parking-card-clear'
        ).click()
        page.wait_for_function(
            "(n) => document.querySelector('#parking-total-count').innerText.startsWith(String(n))",
            arg=before - 1,
            timeout=10_000,
        )
        page.locator("#parking-undo-clear").click()
        page.wait_for_function(
            "(n) => document.querySelector('#parking-total-count').innerText.startsWith(String(n))",
            arg=before,
            timeout=10_000,
        )

        # --- a chosen subset ---
        page.locator("#parking-select-mode").click()
        page.locator(
            '#parking-panel .parking-card:has-text("Spark shuffle") .parking-card-check'
        ).check()
        page.locator(
            '#parking-panel .parking-card:has-text("dbt tests") .parking-card-check'
        ).check()
        assert page.locator("#parking-selected-count").inner_text() == "2 selected"
        page.locator("#parking-clear-selected").click()
        page.wait_for_function(
            "(n) => document.querySelector('#parking-total-count').innerText.startsWith(String(n))",
            arg=before - 2,
            timeout=10_000,
        )
        survivors = {
            item["question"]
            for column in _api(page, "/api/parking/board")["columns"]
            for item in column["items"]
        }
        assert "Spark shuffle" not in survivors and "dbt tests" not in survivors
        assert STUDY_TOPIC in survivors, "the wrong subset was cleared"
        page.locator("#parking-undo-clear").click()
        page.wait_for_function(
            "(n) => document.querySelector('#parking-total-count').innerText.startsWith(String(n))",
            arg=before,
            timeout=10_000,
        )
    except Exception:
        _diag(page, "phase8b")
        raise


# ---------------------------------------------------------------------------
# Phase 9 — durability
# ---------------------------------------------------------------------------


def test_phase9_everything_survives_a_reload(page: Page, bd_env: RunningServer) -> None:
    """It is in the DB, not in the DOM — and the journey itself was error-free."""
    try:
        # The strong claim first: eight phases of real interaction with no
        # console errors at all.
        journey_errors = list(getattr(page, "_studyloop_errors", []))
        assert not journey_errors, f"the journey produced console errors: {journey_errors}"

        # End the session through the UI before reloading.
        #
        # Two reasons. It exercises the end path, which nothing else here does.
        # And it keeps this phase about ONE thing: whether the notes, parked
        # topics and focus contract are durable. Reloading with a session still
        # live also drags in WebSocket *reattachment*, which is currently broken
        # for an unrelated reason — the server's detach-grace work refuses the
        # second attach with a 403 while the previous connection's attach entry
        # is still held (see
        # docs/handoffs/2026-08-04-ws-refresh-destroys-session-handoff.md,
        # "Diagnosed, reproduced, not fixed"). That belongs to that change and
        # its own test module; a durability test failing for it would be
        # reporting the wrong defect.
        _open_body_double(page, bd_env)
        # Deterministic, not best-effort. This used to be wrapped in
        # `if is_visible()`, which meant the ONLY actuation of #bd-end-session
        # in the whole suite silently no-op'd whenever the session had already
        # gone — so the end path could rot without anything failing.
        assert page.locator("#bd-end-session").is_visible(), (
            "phase 3 started a session; it should still be live here"
        )
        page.locator("#bd-end-session").click()
        # Ending kills a live agent and its PTY, so it confirms first.
        page.wait_for_selector("#bd-end-confirm", state="visible", timeout=5_000)
        page.locator("#bd-end-confirm-yes").click()
        page.wait_for_selector("#bd-end-session", state="hidden", timeout=15_000)

        errors_before_reload = len(getattr(page, "_studyloop_errors", []))
        page.reload()
        page.wait_for_function("() => !!window.Alpine", timeout=15_000)
        _open_body_double(page, bd_env)

        # The focus contract is rebuilt from the two DBs, not from memory.
        page.wait_for_function(
            "() => document.querySelector('#bd-focus-count').innerText === '3 of 3 topics'",
            timeout=15_000,
        )
        _open_notes_panel(page)
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '4 notes'",
            timeout=15_000,
        )
        card = page.locator('#notes-panel .note-card:has-text("Decorator call order")').first
        card.locator(".note-card-title").click()
        page.wait_for_function(
            """(id) => {
                const c = document.querySelector(
                    '#notes-panel .note-card[data-id="' + id + '"]');
                const r = c && c.querySelector('.note-rendered');
                return !!r && !!r.querySelector('svg');
            }""",
            arg=card.get_attribute("data-id"),
            timeout=15_000,
        )
        assert card.locator(".note-rendered table").count() == 1

        # The parked tangent is still on the board too.
        _open_parking_panel(page)
        page.locator(
            '#parking-panel .parking-card:has-text("Class-based decorators")'
        ).first.wait_for(state="visible", timeout=15_000)

        # Post-reload the only tolerated noise is htmx reconnecting its SSE
        # activity stream, which legitimately owns a connection across a reload
        # and logs a bare `Event`. Anything else is a real error.
        post_reload = [
            err
            for err in getattr(page, "_studyloop_errors", [])[errors_before_reload:]
            if not ("Event" in err and "htmx" in err)
        ]
        assert not post_reload, f"reload produced unexpected console errors: {post_reload}"
    except Exception:
        _diag(page, "phase9")
        raise
