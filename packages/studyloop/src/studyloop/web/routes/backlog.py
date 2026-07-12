"""Backlog / parking-lot API — makes the 3-topic rule visible to the learner.

The AuDHD design keeps at most ``MAX_ACTIVE_TOPICS`` topics in focus; everything
else lives in a visible parking lot rather than competing for attention. This
endpoint returns that split so the web UI (and MCP ``get_active_topics``) can
surface "these 3 are live, the rest are parked" instead of an undifferentiated
list.
"""

from __future__ import annotations

from fastapi import APIRouter

from studyloop.parking import get_parked_topics
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
