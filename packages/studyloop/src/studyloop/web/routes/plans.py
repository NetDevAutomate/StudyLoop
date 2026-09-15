"""Study-plan API routes.

Read paths serve both the parsed summary (for list rendering) and the raw
Markdown (for the client-side ``marked → DOMPurify → hljs/mermaid`` pipeline the
Course Explorer already uses), so the plan renders as a proper document rather
than a bespoke widget.

Write paths are deliberately narrow: create from an interview payload, patch
metadata/milestones, set one milestone, run an evaluation checkpoint, delete.
Free-form Markdown replacement is allowed but validated by re-parsing, so a
malformed body is rejected instead of corrupting a plan.

Policy lives in :class:`~studyloop.planning.PlanApplication`, not here. Every
path that can make a plan active — create-with-status, document import,
whole-document replacement, status transition, and any in-place revision of a
plan that is or becomes active — goes through ``apply`` and is refused by the
same readiness gate with the same 422 body. Evaluation goes through ``assess``
and reports both recording sinks; the milestone checkbox is an idempotent
``SetMilestone``; ``DELETE`` is a confirmed ``DeletePlan`` — the HTTP verb is
the confirmation this route contract has always had. This module only maps
domain errors to status codes (design §2) and translates bodies; it holds no
rule of its own and imports no storage module (D-6).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from studyloop.planning import (
    PLAN_STATUSES,
    AssessmentResult,
    AssessPlan,
    CreatePlan,
    DeletePlan,
    ImportDocument,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanApplication,
    PlanConflict,
    PlanDetail,
    PlanDetailIntent,
    PlanError,
    PlanIntent,
    PlanNotFound,
    PlanNotReady,
    ReplaceDocument,
    RevisePlan,
    SetMilestone,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Seam access and the one error mapping (design §2)
# ---------------------------------------------------------------------------


def _application() -> PlanApplication:
    return PlanApplication()


def _http_error(exc: PlanError) -> HTTPException:
    """Map a domain refusal to its status code — the only place this happens."""
    if isinstance(exc, PlanNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidPlanId | InvalidField):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PlanConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PlanNotReady):
        return HTTPException(
            status_code=422,
            detail={"message": str(exc), **exc.readiness.to_json_dict()},
        )
    if isinstance(exc, InvalidMilestone):
        return HTTPException(status_code=404, detail=str(exc))
    logger.error("unmapped plan error %s", type(exc).__name__, exc_info=exc)
    return HTTPException(status_code=500, detail="plan operation failed")


def _inspect(plan_id: str, **options: Any) -> PlanDetail:
    try:
        return _application().inspect(plan_id, **options)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _apply(intent: PlanDetailIntent) -> PlanDetail:
    try:
        return _application().apply(intent)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _assess(intent: AssessPlan) -> AssessmentResult:
    try:
        return _application().assess(intent)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _written(detail: PlanDetail, **flags: bool) -> dict[str, Any]:
    """The body every successful write returns: a flag, the summary, readiness."""
    return {
        **flags,
        "plan": detail.summary.to_json_dict(),
        "readiness": detail.readiness.to_json_dict(),
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/plans")
def get_plans(
    status: str = Query("", pattern="^(|draft|active|paused|complete|abandoned)$"),
) -> dict:
    """List plans (summaries only) for the left-pane Study Plan section."""
    try:
        plans = _application().browse(status=status or None)
    except PlanError as exc:  # pragma: no cover - the Query pattern already refuses
        raise _http_error(exc) from exc
    return {
        "plans": [plan.to_json_dict() for plan in plans],
        "count": len(plans),
        "statuses": list(PLAN_STATUSES),
    }


@router.get("/plans/interview")
def get_interview() -> dict:
    """Return the plan-creation interview plus data-grounded seed suggestions."""
    brief = _application().prepare_planning().to_json_dict()
    return {"questions": brief["questions"], "seed": brief["seed"]}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str) -> dict:
    """Return one plan: parsed structure, raw Markdown, and readiness."""
    return _inspect(plan_id, include_markdown=True).to_json_dict()


@router.get("/plans/{plan_id}/markdown", response_class=PlainTextResponse)
def get_plan_markdown(plan_id: str) -> str:
    """Raw Markdown for a plan — the download / copy-to-agent path."""
    markdown = _inspect(plan_id, include_markdown=True).markdown
    return markdown or ""


@router.get("/plans/{plan_id}/history")
def get_plan_history(plan_id: str, limit: int = Query(20, ge=1, le=200)) -> dict:
    """Durable checkpoint log from the sessions DB."""
    detail = _inspect(plan_id, include_history=True, history_limit=limit)
    return {
        "plan_id": plan_id,
        "checkpoints": [entry.to_json_dict() for entry in detail.history or ()],
    }


# ---------------------------------------------------------------------------
# Evaluation — the three session checkpoints
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}/evaluate")
def preview_evaluation(
    plan_id: str,
    phase: str = Query("start", pattern="^(start|mid|end)$"),
) -> dict:
    """Evaluate without recording — safe to poll from the UI."""
    result = _assess(AssessPlan(plan_id=plan_id, phase=phase, record=False))
    return {"evaluation": result.evaluation.to_json_dict(), "markdown": result.evaluation.markdown}


@router.post("/plans/{plan_id}/evaluate", status_code=201)
def record_evaluation(plan_id: str, payload: Annotated[dict | None, Body()] = None) -> dict:
    """Run and record a checkpoint (DB log + appended to the plan document).

    ``recorded`` is honest: ``true`` only when every requested sink was saved.
    The two sinks are reported individually so a client can tell "the plan
    document has the row but the database does not" from the reverse, instead
    of reading a bare ``true`` that Bug B (issue #7) showed could be a lie.
    """
    payload = payload or {}
    result = _assess(
        AssessPlan(
            plan_id=plan_id,
            phase=str(payload.get("phase", "start")),
            study_id=str(payload.get("study_id", "")),
            record=True,
            append_to_plan=bool(payload.get("append_to_plan", True)),
        )
    )
    return {
        "recorded": result.recording_complete,
        "db_write": result.db_write,
        "document_write": result.document_write,
        "evaluation": result.evaluation.to_json_dict(),
        "markdown": result.evaluation.markdown,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.post("/plans", status_code=201)
def post_plan(payload: Annotated[dict, Body()]) -> dict:
    """Create a plan from interview answers, or from raw Markdown.

    ``{"markdown": "..."}`` imports a document verbatim (validated by
    re-parsing).  Otherwise ``{"title", "answers"}`` drafts one from the
    interview, which is what the agent and the UI wizard both use. Either way
    a document that would be active is readiness-gated by the seam (422).
    """
    plan_id = str(payload.get("plan_id", "")).strip() or None
    overwrite = bool(payload.get("overwrite", False))
    raw_markdown = payload.get("markdown")
    intent: PlanIntent
    if raw_markdown:
        intent = ImportDocument(markdown=str(raw_markdown), plan_id=plan_id, overwrite=overwrite)
    else:
        intent = CreatePlan(
            title=str(payload.get("title", "")),
            answers=payload.get("answers") or {},
            plan_id=plan_id,
            status=str(payload.get("status", "draft")),
            overwrite=overwrite,
        )
    return _written(_apply(intent), created=True)


@router.patch("/plans/{plan_id}")
def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
    """Update plan fields in place.

    Accepts ``status``, ``title``, ``topics``, ``target_date``,
    ``energy_floor``, ``review_cadence_days``, ``notes``, ``milestones``
    (full replacement), and ``markdown`` (whole-document replacement).

    The non-Markdown body is *one* ``RevisePlan``: the seam loads the plan
    once, applies every supplied field, judges the resulting document — so
    ``{"status": "active", "milestones": []}`` is refused, and a field-only
    edit cannot leave an active plan unevaluable — and saves once. The route
    translates the body; it validates and writes nothing itself.
    """
    if "markdown" in payload:
        replaced = _apply(ReplaceDocument(plan_id=plan_id, markdown=str(payload["markdown"])))
        return _written(replaced, updated=True)

    # ``None`` is "leave as is" for the seam, and a key that is absent from the
    # body is exactly that. (A key explicitly set to ``null`` reads the same.)
    revision = RevisePlan(
        plan_id=plan_id,
        title=payload.get("title"),
        topics=payload.get("topics"),
        target_date=payload.get("target_date"),
        energy_floor=payload.get("energy_floor"),
        review_cadence_days=payload.get("review_cadence_days"),
        notes=payload.get("notes"),
        milestones=payload.get("milestones"),
        status=payload.get("status"),
    )
    return _written(_apply(revision), updated=True)


@router.post("/plans/{plan_id}/milestones/{index}/toggle")
def toggle_milestone(plan_id: str, index: int) -> dict:
    """Flip one milestone's done state — the checkbox in the plan view.

    The route reads the current state and asks the seam to *set* its
    opposite: ``SetMilestone`` is idempotent, so a retried request cannot
    flip the box twice, and the index check is the seam's — an index the plan
    does not have is ``InvalidMilestone`` (404), never a route-side rule.
    """
    current = _inspect(plan_id)
    already_done = any(m.index == index and m.done for m in current.milestones)
    updated = _apply(SetMilestone(plan_id=plan_id, index=index, done=not already_done))
    return {
        "updated": True,
        "index": index,
        "done": updated.milestones[index].done,
        "plan": updated.summary.to_json_dict(),
    }


@router.delete("/plans/{plan_id}")
def remove_plan(plan_id: str) -> dict:
    """Delete a plan document. Checkpoint history is intentionally retained.

    The ``DELETE`` verb is the confirmation this route has always required, so
    the intent is applied confirmed; the seam still refuses an unknown id
    (404) or a malformed one (400) before anything is removed.
    """
    try:
        result = _application().apply(DeletePlan(plan_id=plan_id, confirmed=True))
    except PlanError as exc:
        raise _http_error(exc) from exc
    return result.to_json_dict()
