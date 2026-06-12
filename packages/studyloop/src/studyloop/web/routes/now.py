"""Current-study recommendation API."""

from __future__ import annotations

from fastapi import APIRouter, Query

from studyloop.learning.decision import build_now_plan

router = APIRouter()


@router.get("/now")
def get_now(
    energy: str = Query("medium", pattern="^(low|medium|high)$"),
    time: int = Query(25, ge=5, le=180),
    modality: str = Query(
        "recall",
        pattern="^(recall|conversation|hands-on|visual|audio)$",
    ),
    interleave: str = Query("off", pattern="^(off|adaptive)$"),
) -> dict:
    """Return the same recommendation contract as ``studyloop now --json``."""
    plan = build_now_plan(
        energy=energy,  # type: ignore[arg-type]
        time_minutes=time,
        modality=modality,  # type: ignore[arg-type]
        interleave=interleave,  # type: ignore[arg-type]
    )
    return plan.to_json_dict()
