"""Issue #30 — the first move reaches the Body Double view and the Today card.

``components.js`` (where ``bodyDoubleSession()`` lives) has no node-test harness,
so its side of the hand-off is pinned statically here: the ``body-double-request``
listener must read ``detail.firstMove``, the picker must show it beside the
activity, and the Today card must render its own first-move line. These are
markup contracts, not behaviour tests — the behaviour lives in
``tests/js/today-panel-plan.test.js`` (the dispatching side) and in the engine
tests that derive the sentence.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _listener(js: str) -> str:
    start = js.index("window.addEventListener('body-double-request'")
    depth = 0
    for i in range(start, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i]
    raise AssertionError("unterminated body-double-request listener")


def test_body_double_view_takes_the_first_move_from_the_today_hand_off() -> None:
    js = _read("components.js")
    listener = _listener(js)
    assert "detail.firstMove" in listener, "the listener ignores the first move"
    assert re.search(r"this\.firstMove\s*=", listener), "the first move is not stored on the view"
    # The view's initial state declares the field, so a hand-off without one shows nothing.
    session = js[js.index("function bodyDoubleSession()") :]
    assert re.search(r"\bfirstMove:\s*''", session[:6000]), (
        "bodyDoubleSession() lacks firstMove: ''"
    )


def test_body_double_picker_shows_the_first_move_beside_the_activity() -> None:
    html = _read("index.html")
    picker_start = html.index('class="bd-card bd-start-picker"')
    picker = html[picker_start : html.index("</section>", picker_start)]
    match = re.search(r'<p[^>]*id="bd-first-move"[^>]*>', picker)
    assert match, "the picker has no #bd-first-move element"
    tag = match.group(0)
    assert 'x-show="firstMove"' in tag and 'x-text="firstMove"' in tag
    assert picker.index('id="bd-activity-input"') < match.start(), (
        "the move sits under the activity"
    )


def test_today_card_renders_the_first_move_as_its_own_line() -> None:
    html = _read("index.html")
    card_start = html.index("Your one next action")
    card = html[card_start : html.index("</div>", html.index('class="today-reason"', card_start))]
    match = re.search(r'<p[^>]*class="today-first-move"[^>]*>', card)
    assert match, "the Today card has no .today-first-move line"
    tag = match.group(0)
    assert "firstMoveNote(plan?.primary)" in tag or "firstMoveNote(plan.primary)" in tag
    assert "x-show=" in tag, "the line must hide when the payload carries no first move"


# --- Rubric 3c (d2): "Open X" actually opens X ----------------------------------------
#
# Owner 2026-09-21: build the open-the-lesson control, gated behind the evidence
# sentence. The control exists only when a lesson resolved; it asks the Course
# Explorer aside to open that lesson beside the current view (Today or the Body
# Double picker) — the learner does not leave the view. The in-session reader pane
# is #33's, not built here.


def _explorer_component(js: str) -> str:
    start = js.index("function courseExplorer()")
    end = js.index("\nfunction ", start + 1)
    return js[start:end]


def test_course_explorer_opens_a_lesson_by_id_on_request() -> None:
    """The explorer listens for ``explorer-open-lesson`` (detail: ``lessonId``,
    ``title``), opens its aside if it is closed, and calls ``openLesson`` with a
    lesson object built from the id — the same shape ``openSearchResult`` builds."""
    js = _read("components.js")
    explorer = _explorer_component(js)
    assert "window.addEventListener('explorer-open-lesson'" in explorer, (
        "courseExplorer() does not listen for explorer-open-lesson"
    )
    assert re.search(r"openLessonById\s*\(", explorer), "no openLessonById() on the explorer"
    body_start = explorer.index("async openLessonById(")
    body = explorer[body_start : explorer.index("\n    },", body_start)]
    assert "store.open = true" in body or "this.toggle()" in body, "the aside is not opened"
    assert "this.openLesson(" in body, "the lesson is not opened"
    assert "detail.title" in explorer or "title" in body, "the lesson's name is not carried"


def test_body_double_view_takes_the_resolved_lesson_from_the_hand_off() -> None:
    js = _read("components.js")
    listener = _listener(js)
    assert "detail.firstMoveLessonId" in listener, "the listener ignores the lesson id"
    assert re.search(r"this\.firstMoveLessonId\s*=", listener)
    assert re.search(r"this\.firstMoveLessonTitle\s*=", listener)
    session = js[js.index("function bodyDoubleSession()") :]
    assert re.search(r"\bfirstMoveLessonId:\s*''", session[:6000]), (
        "bodyDoubleSession() lacks firstMoveLessonId: ''"
    )
    assert re.search(r"openFirstMoveLesson\s*\(", session), (
        "the Body Double view has no openFirstMoveLesson()"
    )
    body_start = session.index("openFirstMoveLesson(")
    body = session[body_start : session.index("\n    },", body_start)]
    assert "explorer-open-lesson" in body, "the view does not ask the explorer to open the lesson"


def test_body_double_picker_offers_to_open_the_resolved_lesson() -> None:
    html = _read("index.html")
    picker_start = html.index('class="bd-card bd-start-picker"')
    picker = html[picker_start : html.index("</section>", picker_start)]
    match = re.search(r'<button[^>]*id="bd-first-move-open"[^>]*>', picker)
    assert match, "the picker has no #bd-first-move-open control"
    tag = match.group(0)
    assert 'x-show="firstMoveLessonId"' in tag, "the control must exist only when a lesson resolved"
    assert "openFirstMoveLesson()" in tag
    assert picker.index('id="bd-first-move"') < match.start(), "the control sits by the move"


def test_today_card_offers_to_open_the_resolved_lesson() -> None:
    html = _read("index.html")
    card_start = html.index("Your one next action")
    card = html[card_start : html.index("</div>", html.index('class="today-reason"', card_start))]
    match = re.search(r'<button[^>]*data-testid="today-open-first-move-lesson"[^>]*>', card)
    assert match, "the Today card has no open-the-lesson control"
    tag = match.group(0)
    assert "firstMoveLesson(plan?.primary)" in tag, "shown only when a lesson resolved"
    assert "openFirstMoveLesson()" in tag
    line = re.search(r'<p[^>]*class="today-first-move"[^>]*>', card)
    assert line and line.start() < match.start(), "the control sits beside the first-move line"


# --- Rubric 3c (d3): the move survives the start ------------------------------------
#
# Owner 2026-09-21: carry the move and the button into the live session strip.
# Before this, both lived only in the picker (x-show="!sessionActive && !starting"):
# pressing Start hid them at exactly the moment the blank page arrived, and unless
# the lesson had been opened beforehand there was no second chance without ending
# the session. The live strip now carries the same sentence beneath the activity
# name, with the Open-the-lesson control beside it when a lesson resolved — a
# proposal on screen, never something the companion says (the persona's silence
# rule is untouched), and nothing opens by itself: the learner opens the lesson,
# or doesn't. The move arrived with the activity in one hand-off, so it leaves
# with the activity when the session ends — a stale move beneath the next,
# unrelated activity would be a confidently wrong proposal on the one surface
# that is now always on screen.


def _live_strip(html: str) -> str:
    """The live section from its sticky strip to the console that follows it."""
    start = html.index('class="bd-live-strip"')
    return html[start : html.index("<!-- x-if, NOT x-show: this console", start)]


def _method(js: str, name: str) -> str:
    session = js[js.index("function bodyDoubleSession()") :]
    start = session.index(f"{name}(")
    return session[start : session.index("\n    },", start)]


def test_body_double_live_strip_carries_the_first_move_beneath_the_activity() -> None:
    html = _read("index.html")
    strip = _live_strip(html)
    match = re.search(r'<p[^>]*id="bd-live-first-move"[^>]*>', strip)
    assert match, "the live strip has no #bd-live-first-move line"
    tag = match.group(0)
    assert 'x-show="firstMove"' in tag, "the line must hide when no move was handed over"
    line = strip[match.start() : strip.index("</p>", match.start())]
    assert 'x-text="firstMove"' in line, "the line does not carry the same sentence"
    assert strip.index('id="bd-live-activity"') < match.start(), (
        "the move sits beneath the activity name"
    )


def test_body_double_live_strip_offers_to_open_the_resolved_lesson() -> None:
    html = _read("index.html")
    strip = _live_strip(html)
    match = re.search(r'<button[^>]*id="bd-live-first-move-open"[^>]*>', strip)
    assert match, "the live strip has no #bd-live-first-move-open control"
    tag = match.group(0)
    assert 'x-show="firstMoveLessonId"' in tag, "the control must exist only when a lesson resolved"
    assert "openFirstMoveLesson()" in tag, "the control must reuse the view's one opener"
    assert strip.index('id="bd-live-first-move"') < match.start(), (
        "the control sits beside the move"
    )


def test_the_move_leaves_with_the_activity_when_the_session_ends() -> None:
    """``confirmEnd()`` already clears ``activity``; the first move and its lesson
    arrived beside it in the same hand-off and go with it."""
    js = _read("components.js")
    body = _method(js, "async confirmEnd")
    assert "this.activity = ''" in body, "precondition: confirmEnd() clears the activity"
    for field in ("firstMove", "firstMoveLessonId", "firstMoveLessonTitle"):
        assert re.search(rf"this\.{field}\s*=\s*''", body), f"confirmEnd() does not clear {field}"
