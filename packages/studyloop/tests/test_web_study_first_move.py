"""Rubric 3c (e2) — the warm-up follows Start into the Study view (the (d2)+(d3) shape).

Behaviour lives in ``tests/js/session-timer.test.js`` (the hand-off listener, the
opener, the end path) and ``tests/js/today-panel-plan.test.js`` (the dispatch).
These are the MARKUP contracts, pinned here because the markup itself has no
harness: the picker shows the move beneath the topic with the Open-the-lesson
control beside it, and the live layout carries both beneath the status bar for
the whole session — the same two surfaces (d2) and (d3) gave the Body Double.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _study_picker(html: str) -> str:
    start = html.index('class="session-start-picker study-start-picker"')
    return html[start : html.index('class="session-active-layout"', start)]


def _study_live(html: str) -> str:
    start = html.index('class="session-active-layout"')
    return html[start : html.index("STUDY PLANS VIEW", start)]


def test_study_picker_shows_the_first_move_beneath_the_topic() -> None:
    html = _read("index.html")
    picker = _study_picker(html)
    match = re.search(r'<p[^>]*id="study-first-move"[^>]*>', picker)
    assert match, "the Study picker has no #study-first-move line"
    tag = match.group(0)
    assert 'x-show="firstMove"' in tag, "the line must hide when no move was handed over"
    line = picker[match.start() : picker.index("</p>", match.start())]
    assert 'x-text="firstMove"' in line, "the line does not carry the same sentence"
    assert picker.index('id="topic-input"') < match.start(), "the move sits beneath the topic"


def test_study_picker_offers_to_open_the_resolved_lesson() -> None:
    html = _read("index.html")
    picker = _study_picker(html)
    match = re.search(r'<button[^>]*id="study-first-move-open"[^>]*>', picker)
    assert match, "the Study picker has no #study-first-move-open control"
    tag = match.group(0)
    assert 'x-show="firstMoveLessonId"' in tag, "the control must exist only when a lesson resolved"
    assert "openFirstMoveLesson()" in tag, "the control must reuse the view's one opener"
    assert picker.index('id="study-first-move"') < match.start(), "the control sits beside the move"


def test_study_live_layout_carries_the_first_move_beneath_the_status_bar() -> None:
    html = _read("index.html")
    live = _study_live(html)
    match = re.search(r'<(?:p|div)[^>]*id="study-live-first-move"[^>]*>', live)
    assert match, "the live layout has no #study-live-first-move line"
    tag = match.group(0)
    assert 'x-show="firstMove"' in tag
    block = live[match.start() : match.start() + 800]
    assert 'x-text="firstMove"' in block, "the line does not carry the same sentence"
    assert live.index('class="session-status-bar"') < match.start(), (
        "the move sits beneath the status bar that names the topic"
    )
    control = re.search(r'<button[^>]*id="study-live-first-move-open"[^>]*>', block)
    assert control, "the live layout has no #study-live-first-move-open control"
    assert 'x-show="firstMoveLessonId"' in control.group(0)
    assert "openFirstMoveLesson()" in control.group(0)


# --- Council review 8 (2026-09-21): the move never outlives the material it arrived beside --


def test_editing_the_topic_or_changing_the_target_kind_clears_the_move() -> None:
    html = _read("index.html")
    picker = _study_picker(html)
    topic = re.search(r'<input[^>]*id="topic-input"[^>]*>', picker)
    assert topic, "no #topic-input"
    assert "onTopicEdited()" in topic.group(0), "editing the topic does not clear the move"
    kind = re.search(r'<select[^>]*id="target-kind-select"[^>]*>', picker)
    assert kind, "no #target-kind-select"
    assert "clearFirstMove()" in kind.group(0), "changing the target kind does not clear the move"
