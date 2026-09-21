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
