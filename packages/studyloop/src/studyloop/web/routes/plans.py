"""Study-plan API routes.

Read paths serve both the parsed summary (for list rendering) and the raw
Markdown (for the client-side ``marked → DOMPurify → hljs/mermaid`` pipeline the
Course Explorer already uses), so the plan renders as a proper document rather
than a bespoke widget.

Write paths are deliberately narrow: create from an interview payload, patch
metadata/milestones, toggle one milestone, and run an evaluation checkpoint.
Free-form Markdown replacement is allowed but validated by re-parsing, so a
malformed body is rejected instead of corrupting a plan.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from studyloop.planning import (
    CHECKPOINT_PHASES,
    PLAN_STATUSES,
    checkpoint_history,
    create_plan,
    draft_plan,
    evaluate_and_record,
    evaluate_plan,
    interview_spec,
    list_plans,
    load_plan,
    load_plan_text,
    parse_plan,
    readiness,
    save_plan,
    seed_from_history,
    unique_plan_id,
)
from studyloop.planning.store import (
    InvalidPlanIdError,
    PlanExistsError,
    PlanNotFoundError,
    delete_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _load_or_404(plan_id: str):
    try:
        return load_plan(plan_id)
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidPlanIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/plans")
def get_plans(
    status: str = Query("", pattern="^(|draft|active|paused|complete|abandoned)$"),
) -> dict:
    """List plans (summaries only) for the left-pane Study Plan section."""
    plans = list_plans(status=status)
    return {
        "plans": [plan.summary() for plan in plans],
        "count": len(plans),
        "statuses": list(PLAN_STATUSES),
    }


@router.get("/plans/interview")
def get_interview() -> dict:
    """Return the plan-creation interview plus data-grounded seed suggestions."""
    return {"questions": interview_spec(), "seed": seed_from_history()}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str) -> dict:
    """Return one plan: parsed structure, raw Markdown, and readiness."""
    plan = _load_or_404(plan_id)
    return {
        "plan": plan.summary(),
        "markdown": load_plan_text(plan.plan_id),
        "mission": {
            "why": plan.mission.why,
            "success": plan.mission.success,
            "constraints": plan.mission.constraints,
            "out_of_scope": plan.mission.out_of_scope,
        },
        "milestones": [
            {
                "index": i,
                "title": m.title,
                "done": m.done,
                "concepts": m.concepts,
                "notes": m.notes,
            }
            for i, m in enumerate(plan.milestones)
        ],
        "learning_records": [
            {"number": r.number, "title": r.title, "body": r.body, "status": r.status}
            for r in plan.learning_records
        ],
        "resources": [{"label": r.label, "url": r.url, "note": r.note} for r in plan.resources],
        "checkpoints": [
            {
                "phase": c.phase,
                "verdict": c.verdict,
                "at": c.at,
                "summary": c.summary,
                "study_id": c.study_id,
            }
            for c in plan.checkpoints
        ],
        "readiness": readiness(plan),
    }


@router.get("/plans/{plan_id}/markdown", response_class=PlainTextResponse)
def get_plan_markdown(plan_id: str) -> str:
    """Raw Markdown for a plan — the download / copy-to-agent path."""
    _load_or_404(plan_id)
    return load_plan_text(plan_id)


@router.get("/plans/{plan_id}/history")
def get_plan_history(plan_id: str, limit: int = Query(20, ge=1, le=200)) -> dict:
    """Durable checkpoint log from the sessions DB."""
    _load_or_404(plan_id)
    return {"plan_id": plan_id, "checkpoints": checkpoint_history(plan_id, limit=limit)}


# ---------------------------------------------------------------------------
# Evaluation — the three session checkpoints
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}/evaluate")
def preview_evaluation(
    plan_id: str,
    phase: str = Query("start", pattern="^(start|mid|end)$"),
) -> dict:
    """Evaluate without recording — safe to poll from the UI."""
    plan = _load_or_404(plan_id)
    evaluation = evaluate_plan(plan, phase)
    return {"evaluation": evaluation.to_dict(), "markdown": evaluation.as_markdown()}


@router.post("/plans/{plan_id}/evaluate", status_code=201)
def record_evaluation(plan_id: str, payload: Annotated[dict | None, Body()] = None) -> dict:
    """Run and record a checkpoint (DB log + appended to the plan document)."""
    payload = payload or {}
    phase = str(payload.get("phase", "start")).strip().lower()
    if phase not in CHECKPOINT_PHASES:
        raise HTTPException(status_code=400, detail=f"phase must be one of {CHECKPOINT_PHASES}")
    plan = _load_or_404(plan_id)
    evaluation = evaluate_and_record(
        plan,
        phase,
        study_id=str(payload.get("study_id", "")).strip(),
        append_to_plan=bool(payload.get("append_to_plan", True)),
    )
    return {
        "recorded": True,
        "evaluation": evaluation.to_dict(),
        "markdown": evaluation.as_markdown(),
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.post("/plans", status_code=201)
def post_plan(payload: Annotated[dict, Body()]) -> dict:
    """Create a plan from interview answers, or from raw Markdown.

    ``{"markdown": "..."}`` imports a document verbatim (validated by
    re-parsing).  Otherwise ``{"title", "answers"}`` drafts one from the
    interview, which is what the agent and the UI wizard both use.
    """
    raw_markdown = payload.get("markdown")
    if raw_markdown:
        try:
            plan = parse_plan(str(raw_markdown))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
        if not payload.get("plan_id") and not plan.plan_id:
            plan.plan_id = unique_plan_id(plan.title)
    else:
        title = str(payload.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        answers = payload.get("answers") or {}
        if not isinstance(answers, dict):
            raise HTTPException(status_code=400, detail="answers must be an object")
        status = str(payload.get("status", "draft")).strip().lower()
        if status not in PLAN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
        plan = draft_plan(
            title,
            answers,
            plan_id=str(payload.get("plan_id", "")).strip() or unique_plan_id(title),
            status=status,
        )

    try:
        create_plan(plan, overwrite=bool(payload.get("overwrite", False)))
    except PlanExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidPlanIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"created": True, "plan": plan.summary(), "readiness": readiness(plan)}


@router.patch("/plans/{plan_id}")
def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
    """Update plan fields in place.

    Accepts ``status``, ``title``, ``topics``, ``target_date``,
    ``energy_floor``, ``review_cadence_days``, ``notes``, ``milestones``
    (full replacement), and ``markdown`` (whole-document replacement).
    """
    plan = _load_or_404(plan_id)

    if "markdown" in payload:
        try:
            replacement = parse_plan(str(payload["markdown"]), plan_id=plan.plan_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
        replacement.plan_id = plan.plan_id
        replacement.created = plan.created
        save_plan(replacement)
        return {"updated": True, "plan": replacement.summary(), "readiness": readiness(replacement)}

    if "status" in payload:
        status = str(payload["status"]).strip().lower()
        if status not in PLAN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
        if status == "active":
            check = readiness(plan)
            if not check["ready"]:
                raise HTTPException(
                    status_code=422,
                    detail={"message": "plan is not ready to activate", **check},
                )
        plan.status = status

    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        plan.title = title
    if "topics" in payload:
        plan.topics = [str(t).strip() for t in payload["topics"] if str(t).strip()]
    if "target_date" in payload:
        plan.target_date = str(payload["target_date"]).strip()
    if "notes" in payload:
        plan.notes = str(payload["notes"])
    for field_name, lo, hi in (("energy_floor", 1, 10), ("review_cadence_days", 1, 90)):
        if field_name in payload:
            try:
                value = int(payload[field_name])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"{field_name} must be an integer"
                ) from exc
            setattr(plan, field_name, max(lo, min(hi, value)))

    if "milestones" in payload:
        from studyloop.planning.models import Milestone

        items = payload["milestones"]
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="milestones must be a list")
        plan.milestones = [
            Milestone(
                title=str(item.get("title", "")).strip() or "Untitled milestone",
                done=bool(item.get("done", False)),
                concepts=[str(c).strip() for c in (item.get("concepts") or []) if str(c).strip()],
                notes=str(item.get("notes", "")).strip(),
            )
            for item in items
            if isinstance(item, dict)
        ]

    save_plan(plan)
    return {"updated": True, "plan": plan.summary(), "readiness": readiness(plan)}


@router.post("/plans/{plan_id}/milestones/{index}/toggle")
def toggle_milestone(plan_id: str, index: int) -> dict:
    """Flip one milestone's done state — the checkbox in the plan view."""
    plan = _load_or_404(plan_id)
    if index < 0 or index >= len(plan.milestones):
        raise HTTPException(status_code=404, detail=f"no milestone at index {index}")
    plan.milestones[index].done = not plan.milestones[index].done
    save_plan(plan)
    return {
        "updated": True,
        "index": index,
        "done": plan.milestones[index].done,
        "plan": plan.summary(),
    }


@router.delete("/plans/{plan_id}")
def remove_plan(plan_id: str) -> dict:
    """Delete a plan document. Checkpoint history is intentionally retained."""
    try:
        deleted = delete_plan(plan_id)
    except InvalidPlanIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"no study plan with id {plan_id!r}")
    return {"deleted": True, "plan_id": plan_id}
