"""Backlog / parking-lot API — makes the 3-topic rule visible to the learner.

The AuDHD design keeps at most ``MAX_ACTIVE_TOPICS`` topics in focus; everything
else lives in a visible parking lot rather than competing for attention. This
endpoint returns that split so the web UI (and MCP ``get_active_topics``) can
surface "these 3 are live, the rest are parked" instead of an undifferentiated
list.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from studyloop.parking import demote_parked_topic, get_parked_topics, park_topic
from studyloop.settings import MAX_ACTIVE_TOPICS

router = APIRouter()


@router.get("/backlog")
def get_backlog() -> dict:
    """Return pending topics split into active (≤ MAX_ACTIVE_TOPICS) and parking-lot.

    ``active`` is the first ``MAX_ACTIVE_TOPICS`` pending items (most recent
    first); ``parking_lot`` is everything else still pending. Counts are
    included so the UI can show "N parked" without re-counting.
    """
    pending = get_parked_topics(status="pending")
    active = pending[:MAX_ACTIVE_TOPICS]
    parking_lot = pending[MAX_ACTIVE_TOPICS:]
    return {
        "active": active,
        "parking_lot": parking_lot,
        "active_count": len(active),
        "parking_lot_count": len(parking_lot),
        "max_active": MAX_ACTIVE_TOPICS,
    }


class ParkRequest(BaseModel):
    """POST /api/backlog/park request body."""

    question: str = Field(min_length=1, max_length=500)
    tech_area: str | None = None
    context: str | None = None


@router.post("/backlog/park")
def post_park(body: ParkRequest) -> dict:
    """Park a topic/thought for later — the quick-park brain-dump.

    Serves both the global "park a thought" capture (protects flow: the
    learner dumps a tangent without leaving the current task) and the
    park-first friction modal's "park one to free a slot" action.
    """
    row_id = park_topic(
        body.question.strip(),
        tech_area=body.tech_area,
        context=body.context,
        created_by="web",
        source="parked",
    )
    if row_id is None:
        raise HTTPException(status_code=500, detail="Could not park topic")
    return {"ok": True, "id": row_id}


class DemoteRequest(BaseModel):
    """POST /api/backlog/demote request body."""

    id: int


@router.post("/backlog/demote")
def post_demote(body: DemoteRequest) -> dict:
    """Move an ACTIVE topic into the parking lot (frees a 3-topic slot).

    The active/parking split is recency-ordered, so demoting = making the
    row the oldest pending entry. Re-parking the same question via
    /backlog/park would be an INSERT OR IGNORE no-op and would NOT free the
    slot — the park-first friction modal must call this instead.
    """
    if not demote_parked_topic(body.id):
        raise HTTPException(status_code=500, detail="Could not demote topic")
    return {"ok": True}
