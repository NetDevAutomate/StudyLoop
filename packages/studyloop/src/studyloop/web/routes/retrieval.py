"""Where the query encoder's background warm has got to (lane A4, council D-8).

WHY A ROUTE AT ALL. A long-lived server pre-warms the query encoder at boot
(lane A1), which takes seconds and, until this endpoint, was invisible: a
learner searching in that window got a lexical-only answer with no way to tell
whether the semantic arm was still loading, had failed, or was switched off.
This is the same shape as ``GET /api/tts/health`` (E-A8) and for the same
reason: a client that only sees a boolean cannot tell the learner what is
happening or what to fix.

WHY THERE IS NO PERCENTAGE. Nothing in a model load reports its completion
fraction, so a bar would be invented (E-A9). The payload is the honest set: the
phase-level state, which model, how long the load that produced this state took,
and a detail line for the failed/disabled cases.

The payload is exactly ``retrieval.EncoderWarmStatus``'s fields -- a contract
test derives the expected key set from the dataclass, so the browser chip and
the acceptance validators can both cite one schema.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter

router = APIRouter()


@router.get("/retrieval/health")
def retrieval_health() -> dict:
    """The current warm state. Reads status only -- never starts a load.

    Deliberately not a warm TRIGGER (there is no ``POST`` sibling here as there
    is for TTS): the warm belongs to a process-lifetime boundary, server boot,
    not to whoever happens to open a page (grok F10).
    """
    from agent_session_tools import retrieval

    return dataclasses.asdict(retrieval.encoder_warm_status())
