"""Session API routes — live study session dashboard."""

from __future__ import annotations

import asyncio
from html import escape
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from studyctl.session_state import (
    PARKING_FILE,
    STATE_FILE,
    TOPICS_FILE,
    parse_parking_file,
    parse_topics_file,
    read_session_state,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

router = APIRouter()

# Shape → symbol mapping (matches session-protocol.md visual language)
STATUS_SHAPES: dict[str, tuple[str, str]] = {
    "win": ("\u2713", "status-win"),  # ✓
    "insight": ("\u2605", "status-insight"),  # ★
    "learning": ("\u25c6", "status-learning"),  # ◆
    "struggling": ("\u25b2", "status-struggling"),  # ▲
    "parked": ("\u25cb", "status-parked"),  # ○
}


def _get_full_state() -> dict:
    """Read all IPC files into a single state dict."""
    state = read_session_state()
    topics = parse_topics_file()
    parking = parse_parking_file()
    return {
        **state,
        "topics": [
            {"time": t.time, "topic": t.topic, "status": t.status, "note": t.note} for t in topics
        ],
        "parking": [{"question": p.question} for p in parking],
    }


def _render_activity_feed(state: dict) -> str:
    """Render the activity feed HTML fragment (inner content only).

    The SSE swap target already has id="activity-feed", so this returns
    only the *content* to be placed inside that element — not a wrapper div.
    Including a wrapper with the same id would create a duplicate ID when
    HTMX replaces innerHTML of the target.
    """
    topics = state.get("topics", [])
    parking = state.get("parking", [])

    if not topics and not parking:
        return '<p class="activity-empty">Waiting for session activity...</p>'

    items: list[str] = []
    for t in topics:
        status = t.get("status", "learning")
        shape, css_class = STATUS_SHAPES.get(status, ("\u25c6", "status-learning"))
        time_str = escape(t.get("time", ""))
        topic = escape(t.get("topic", ""))
        note = escape(t.get("note", ""))
        display = f"{topic} &mdash; {note}" if note else topic
        items.append(
            f'<div class="activity-item {css_class}">'
            f'<span class="activity-shape">{shape}</span>'
            f'<span class="activity-time">[{time_str}]</span>'
            f'<span class="activity-text">{display}</span>'
            f"</div>"
        )

    for p in parking:
        shape, css_class = STATUS_SHAPES["parked"]
        question = escape(p.get("question", ""))
        items.append(
            f'<div class="activity-item {css_class}">'
            f'<span class="activity-shape">{shape}</span>'
            f'<span class="activity-text">Parked: {question}</span>'
            f"</div>"
        )

    return "\n".join(items)


def _render_counters(state: dict) -> str:
    """Render OOB counter bar fragments."""
    topics = state.get("topics", [])
    wins = sum(1 for t in topics if t.get("status") in ("win", "insight"))
    review = sum(1 for t in topics if t.get("status") == "struggling")
    parked = len(state.get("parking", []))

    return (
        f'<span id="counter-wins" hx-swap-oob="true">'
        f"\u2713 WINS: {wins}</span>"
        f'<span id="counter-parked" hx-swap-oob="true">'
        f"\u25cb PARKED: {parked}</span>"
        f'<span id="counter-review" hx-swap-oob="true">'
        f"\u25b2 REVIEW: {review}</span>"
    )


def _render_session_meta(state: dict) -> str:
    """Render OOB session metadata (energy, topic)."""
    topic = escape(state.get("topic", "No active session"))
    energy = state.get("energy", 5)
    mode = state.get("mode", "")

    if mode == "ended":
        return (
            f'<div id="session-meta" hx-swap-oob="true">'
            f'<span class="meta-topic">{topic}</span>'
            f'<span class="meta-status">Session complete</span>'
            f"</div>"
        )

    return (
        f'<div id="session-meta" hx-swap-oob="true">'
        f'<span class="meta-topic">{topic}</span>'
        f'<span class="meta-energy">'
        f"\u26a1 Energy: {energy}/10</span>"
        f"</div>"
    )


def _render_summary(state: dict) -> str:
    """Render the session-complete summary view."""
    topics = state.get("topics", [])
    parking = state.get("parking", [])
    topic = escape(state.get("topic", "Study Session"))

    wins = [t for t in topics if t.get("status") in ("win", "insight")]
    struggles = [t for t in topics if t.get("status") == "struggling"]

    wins_html = ""
    if wins:
        win_items = "".join(
            f'<li class="status-win">\u2713 {escape(w.get("topic", ""))}'
            f"{' &mdash; ' + escape(w.get('note', '')) if w.get('note') else ''}"
            f"</li>"
            for w in wins
        )
        wins_html = f"<h3>\u2713 Wins</h3><ul>{win_items}</ul>"

    struggles_html = ""
    if struggles:
        struggle_items = "".join(
            f'<li class="status-struggling">\u25b2 {escape(s.get("topic", ""))}</li>'
            for s in struggles
        )
        struggles_html = f"<h3>\u25b2 For Next Session</h3><ul>{struggle_items}</ul>"

    parked_html = ""
    if parking:
        parked_items = "".join(
            f'<li class="status-parked">\u25cb {escape(p.get("question", ""))}</li>'
            for p in parking
        )
        parked_html = f"<h3>\u25cb Parked Topics</h3><ul>{parked_items}</ul>"

    return (
        f'<div class="session-summary">'
        f'<div class="summary-header">'
        f"<h2>Session Complete: {topic}</h2>"
        f"</div>"
        f"{wins_html}{struggles_html}{parked_html}"
        f'<p class="summary-cta">'
        f"Stand up. Walk to the kitchen. Your brain needs a break.</p>"
        f"</div>"
    )


def _render_update(state: dict) -> str:
    """Render a full SSE update payload (activity + OOB counters + meta)."""
    if state.get("mode") == "ended":
        return _render_summary(state) + _render_counters(state)
    return _render_activity_feed(state) + _render_counters(state) + _render_session_meta(state)


@router.get("/session/state")
def get_session_state() -> dict:
    """JSON endpoint for initial session state load."""
    return _get_full_state()


@router.get("/session/stream")
async def session_stream(request: Request) -> StreamingResponse:
    """SSE endpoint for live session updates.

    Polls IPC files every 2 seconds and pushes HTML fragments
    when changes are detected. HTMX SSE extension swaps the
    primary target; OOB attributes update counters and metadata.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        last_mtimes: tuple[float, float, float] = (0.0, 0.0, 0.0)
        while True:
            if await request.is_disconnected():
                break
            # O(1) change detection: 3 stat() calls instead of full JSON serialisation
            mtimes = tuple(
                f.stat().st_mtime if f.exists() else 0.0
                for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE)
            )
            if mtimes != last_mtimes:
                state = _get_full_state()
                html = _render_update(state)
                # SSE format: event name + data (newlines in data escaped)
                escaped = html.replace("\n", "")
                yield f"event: session-update\ndata: {escaped}\n\n"
                last_mtimes = mtimes  # type: ignore[assignment]
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
