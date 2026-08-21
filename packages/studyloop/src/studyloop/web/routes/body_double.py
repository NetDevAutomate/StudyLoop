"""Body-double focus API — what am I allowed to be working on right now?

Body doubling is presence plus a clock. The failure mode it does *not* protect
against on its own is the AuDHD one: sitting down with a timer running and
quietly acquiring a fourth, fifth, sixth "current" topic. So the Body Double
surface gets a focus contract, and this is the endpoint behind it.

It answers one question — *"which at-most-three topics are live, and what does
the history say about them?"* — by joining three sources that already exist
rather than inventing a fourth store:

* **config focus** (``studyloop focus set``) — topics the learner explicitly
  committed to. Authoritative when present, because it is a deliberate choice
  rather than a side effect of what happened to get studied.
* **the parking lot** (``parked_topics`` in the session DB) — the recency-ordered
  pending list whose first ``MAX_ACTIVE_TOPICS`` entries *are* the live slots.
  This is the same split ``/api/backlog`` serves, so the 3-topic rule means the
  same thing on both surfaces.
* **the sessions DB** (``study_sessions`` / ``study_progress``) — how recently
  each topic was actually studied, and whether it is a current repair target.
  That is what makes the panel say "you last touched this 9 days ago" instead of
  just listing strings.

``GET /api/body-double/focus`` is read-only and degrades: every source is
wrapped, and a missing DB yields empty lists rather than a 500, because a body
double session must be startable on a fresh machine.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from studyloop.settings import MAX_ACTIVE_TOPICS

logger = logging.getLogger(__name__)

router = APIRouter()


def _config_focus() -> dict[str, Any]:
    """Read the explicitly-committed focus topics from config.yaml."""
    try:
        from studyloop.focus import get_focus

        state = get_focus()
        return {
            "topics": list(state.topics),
            "updated": state.updated,
            "is_set": state.is_set,
            "is_stale": state.is_stale,
        }
    except Exception:
        logger.debug("focus config unavailable", exc_info=True)
        return {"topics": [], "updated": None, "is_set": False, "is_stale": False}


def _parked_split() -> tuple[list[dict], list[dict]]:
    """Return ``(active, parked)`` pending topics under the 3-topic rule."""
    try:
        from studyloop.parking import get_parked_topics

        pending = get_parked_topics(status="pending")
    except Exception:
        logger.debug("parking lot unavailable", exc_info=True)
        return [], []
    return pending[:MAX_ACTIVE_TOPICS], pending[MAX_ACTIVE_TOPICS:]


def _recent_session_topics(days: int = 30, limit: int = 8) -> list[dict[str, Any]]:
    """Recent study-session topics from the sessions DB, most-studied first."""
    try:
        from studyloop.focus import suggest_focus

        return [
            {"topic": topic, "evidence": evidence}
            for topic, evidence in suggest_focus(days=days, limit=limit)
        ]
    except Exception:
        logger.debug("session-topic suggestions unavailable", exc_info=True)
        return []


def _struggle_topics(days: int = 30) -> list[dict[str, Any]]:
    """Current repair targets — what the history says is not sticking yet."""
    try:
        from studyloop.history.progress import get_struggling_topics

        rows = get_struggling_topics(days=days)
    except Exception:
        logger.debug("struggle topics unavailable", exc_info=True)
        return []
    out: list[dict[str, Any]] = []
    for row in rows[:8]:
        if isinstance(row, dict):
            topic = row.get("topic") or row.get("concept")
            if topic:
                out.append({"topic": str(topic), "detail": row})
    return out


def _note_counts() -> dict[str, int]:
    """How many notes exist per topic — a topic with notes has traction."""
    try:
        from studyloop.notes import list_notes

        counts: dict[str, int] = {}
        for note in list_notes(limit=500):
            topic = (note.get("topic") or "").strip()
            if topic:
                counts[topic] = counts.get(topic, 0) + 1
        return counts
    except Exception:
        logger.debug("note counts unavailable", exc_info=True)
        return {}


@router.get("/body-double/focus")
def get_body_double_focus() -> dict:
    """Return the focus contract for a body-double session.

    ``slots`` is the answer the UI renders: at most ``MAX_ACTIVE_TOPICS`` entries,
    each annotated with why it is live and what the history knows about it.
    ``at_capacity`` is the flag that drives the park-first prompt — the caller
    does not have to re-derive the rule from the counts.
    """
    focus = _config_focus()
    active, parked = _parked_split()
    recent = _recent_session_topics()
    struggles = _struggle_topics()
    note_counts = _note_counts()

    struggle_names = {s["topic"].lower() for s in struggles}
    recent_by_name = {r["topic"].lower(): r["evidence"] for r in recent}

    def _annotate(topic: str, source: str, row: dict | None = None) -> dict[str, Any]:
        key = topic.lower()
        return {
            "topic": topic,
            "source": source,
            "id": (row or {}).get("id"),
            "tech_area": (row or {}).get("tech_area"),
            "note_count": note_counts.get(topic, 0),
            "is_struggle": key in struggle_names,
            "last_studied": recent_by_name.get(key),
        }

    # Config focus wins: it is a deliberate commitment, not an accident of
    # what got studied. Parked-active topics fill any remaining slots so the
    # panel is never empty just because `studyloop focus set` was never run.
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for topic in focus["topics"]:
        if topic.lower() not in seen:
            slots.append(_annotate(topic, "focus"))
            seen.add(topic.lower())
    for row in active:
        topic = (row.get("question") or "").strip()
        if topic and topic.lower() not in seen and len(slots) < MAX_ACTIVE_TOPICS:
            slots.append(_annotate(topic, "active", row))
            seen.add(topic.lower())

    return {
        "max_active": MAX_ACTIVE_TOPICS,
        "slots": slots[:MAX_ACTIVE_TOPICS],
        "slots_used": len(slots[:MAX_ACTIVE_TOPICS]),
        "slots_free": max(0, MAX_ACTIVE_TOPICS - len(slots[:MAX_ACTIVE_TOPICS])),
        "at_capacity": len(slots) >= MAX_ACTIVE_TOPICS,
        "focus": focus,
        "active": active,
        "parking_lot": parked,
        "parking_lot_count": len(parked),
        "recent_topics": recent,
        "struggles": [s["topic"] for s in struggles],
        "note_counts": note_counts,
    }


class FocusSet(BaseModel):
    """POST /api/body-double/focus — commit up to MAX_ACTIVE_TOPICS topics."""

    topics: list[str] = Field(default_factory=list)


@router.post("/body-double/focus")
def set_body_double_focus(body: FocusSet) -> dict:
    """Commit the focus topics for this stretch of work.

    Enforcing the cap server-side (not only in the picker) is the point: the
    rule of 3 has to hold for the MCP agent and a future mobile client too, not
    just for whoever is looking at the web UI.
    """
    cleaned = [t.strip() for t in body.topics if t and t.strip()]
    if len(cleaned) > MAX_ACTIVE_TOPICS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Maximum {MAX_ACTIVE_TOPICS} focus topics — park one before "
                "adding another. Fewer active topics means faster progress."
            ),
        )
    try:
        from studyloop.focus import clear_focus, set_focus

        if not cleaned:
            clear_focus()
        else:
            set_focus(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - config write failure
        raise HTTPException(status_code=500, detail="Could not save focus") from exc
    return {"ok": True, "topics": cleaned, "max_active": MAX_ACTIVE_TOPICS}
