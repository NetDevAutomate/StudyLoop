"""Study-plan API routes.

Read paths serve both the parsed summary (for list rendering) and the raw
Markdown (for the client-side ``marked → DOMPurify → hljs/mermaid`` pipeline the
Course Explorer already uses), so the plan renders as a proper document rather
than a bespoke widget.

Compatibility writes translate into typed lifecycle commands. Structural
creation and revision require exact learner decisions; checkpoints, milestone
outcomes, status transitions, imports, and abandonment keep their distinct
authority and evidence rules.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from studyloop.planning import (
    CHECKPOINT_PHASES,
    PLAN_STATUSES,
    ActorContext,
    DecideProposal,
    ImportPlanDraft,
    LifecycleError,
    PlanCapacityError,
    PlanConflictError,
    PlanningCommand,
    PlanningRepositoryError,
    PlanningRequest,
    ProposalConflictError,
    ProposalRef,
    RecordCheckpoint,
    RecordMilestoneOutcome,
    SubmitProposalDraft,
    TransitionPlanStatus,
    checkpoint_history,
    draft_plan,
    evaluate_plan,
    interview_spec,
    list_plans,
    load_plan,
    load_plan_text,
    parse_plan,
    readiness,
    seed_from_history,
    unique_plan_id,
)
from studyloop.planning.compat import (
    PreferredPlanIdGenerator,
    outcome_payload,
    proposal_draft_from_plan,
    proposal_payload,
    require_outcome,
    require_proposal,
)
from studyloop.planning.index import record_checkpoint
from studyloop.planning.runtime import planning_lifecycle
from studyloop.planning.store import (
    InvalidPlanIdError,
    PlanNotFoundError,
)
from studyloop.web.learner_auth import require_browser_learner

logger = logging.getLogger(__name__)

router = APIRouter()

_WEB_MODEL = ActorContext("model", "compatibility-translator", "web")
_WEB_RECORDER = ActorContext("recorder", "studyloop", "web")


def _request_key(payload: dict, prefix: str) -> str:
    supplied = str(payload.get("idempotency_key", "")).strip()
    return f"{prefix}:{supplied or uuid.uuid4().hex}"


def _raise_lifecycle(exc: Exception) -> NoReturn:
    if isinstance(exc, (PlanCapacityError, PlanConflictError, ProposalConflictError)) or (
        isinstance(exc, LifecycleError) and "terminal status" in str(exc)
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (LifecycleError, PlanningRepositoryError, InvalidPlanIdError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _plan_decision(value: object) -> Literal["approve", "reject"]:
    decision = str(value or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be approve or reject")
    return decision  # type: ignore[return-value]


def _milestone_outcome(
    value: object,
) -> Literal["verified_complete", "learner_attested", "incomplete"]:
    outcome = str(value or "").strip().lower()
    if outcome not in {"verified_complete", "learner_attested", "incomplete"}:
        raise HTTPException(status_code=400, detail="unsupported milestone outcome")
    return outcome  # type: ignore[return-value]


def _plan_response(plan_id: str) -> dict:
    plan = _load_or_404(plan_id)
    return {"plan": plan.summary(), "readiness": readiness(plan)}


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
    current = [plan for plan in list_plans() if plan.status in {"draft", "active", "paused"}]
    return {
        "plans": [plan.summary() for plan in plans],
        "count": len(plans),
        "statuses": list(PLAN_STATUSES),
        "capacity": {
            "current": len(current),
            "max": 3,
            "available": max(0, 3 - len(current)),
            "can_create": len(current) < 3,
        },
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
    """Run and record a checkpoint through the authoritative lifecycle."""
    payload = payload or {}
    phase = str(payload.get("phase", "start")).strip().lower()
    if phase not in CHECKPOINT_PHASES:
        raise HTTPException(status_code=400, detail=f"phase must be one of {CHECKPOINT_PHASES}")
    plan = _load_or_404(plan_id)
    study_id = str(payload.get("study_id", "")).strip()
    evaluation = evaluate_plan(plan, phase, study_id=study_id)
    if str(payload.get("idempotency_key", "")).strip():
        prior = next(
            (
                item
                for item in reversed(plan.checkpoints)
                if item.phase == phase and item.study_id == study_id
            ),
            None,
        )
        if prior is not None:
            evaluation.at = prior.at
    command_key = _request_key(payload, "web-checkpoint")
    try:
        outcome = require_outcome(
            planning_lifecycle(evidence=plan.evidence).handle(
                PlanningCommand(
                    _WEB_RECORDER,
                    RecordCheckpoint(
                        plan.plan_id,
                        evaluation.to_checkpoint(),
                        command_key,
                    ),
                ),
            )
        )
    except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
        _raise_lifecycle(exc)
    try:
        if not record_checkpoint(evaluation, study_id=study_id, idempotency_key=command_key):
            evaluation.warnings.append("checkpoint not saved to the database")
    except Exception:
        logger.debug("checkpoint DB write failed", exc_info=True)
        evaluation.warnings.append("checkpoint not saved to the database")
    return {
        "recorded": True,
        "outcome": outcome_payload(outcome),
        "evaluation": evaluation.to_dict(),
        "markdown": evaluation.as_markdown(),
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.post("/plans", status_code=201)
def post_plan(request: Request, payload: Annotated[dict, Body()], response: Response) -> dict:
    """Compatibility create/import adapter backed only by the lifecycle."""
    if {"actor", "actor_kind", "role"} & set(payload):
        raise HTTPException(status_code=400, detail="request payload cannot choose actor authority")
    if payload.get("overwrite"):
        raise HTTPException(status_code=400, detail="overwrite is not supported")
    if payload.get("proposal_id"):
        learner = require_browser_learner(request)
        try:
            service = planning_lifecycle()
            review = require_proposal(service.inspect(ProposalRef(str(payload["proposal_id"]))))
            if review.mode != "create":
                raise HTTPException(
                    status_code=409,
                    detail="POST /plans can decide only a creation proposal",
                )
            outcome = require_outcome(
                service.handle(
                    PlanningCommand(
                        learner,
                        DecideProposal(
                            review.proposal_id,
                            str(payload.get("proposal_digest", "")),
                            _plan_decision(payload.get("decision")),
                            _request_key(payload, "web-create-decision"),
                        ),
                    ),
                )
            )
        except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
            _raise_lifecycle(exc)
        body = {"outcome": outcome_payload(outcome)}
        if outcome.status == "applied":
            body.update(_plan_response(outcome.plan_id))
        return body

    raw_markdown = payload.get("markdown")
    if raw_markdown:
        learner = require_browser_learner(request)
        try:
            outcome = require_outcome(
                planning_lifecycle().handle(
                    PlanningCommand(
                        learner,
                        ImportPlanDraft(
                            str(raw_markdown),
                            _request_key(payload, "web-import"),
                        ),
                    ),
                )
            )
        except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
            _raise_lifecycle(exc)
        return {"outcome": outcome_payload(outcome), **_plan_response(outcome.plan_id)}

    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        raise HTTPException(status_code=400, detail="answers must be an object")
    if str(payload.get("status", "draft")).strip().lower() != "draft":
        raise HTTPException(status_code=400, detail="new compatibility plans are always drafts")
    if str(payload.get("decision", "")).strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "creation approval must be a separate request containing the displayed "
                "proposal_id and proposal_digest"
            ),
        )
    plan = draft_plan(
        title,
        answers,
        plan_id=str(payload.get("plan_id", "")).strip() or unique_plan_id(title),
        status="draft",
    )
    key = _request_key(payload, "web-create")
    try:
        service = planning_lifecycle(ids=PreferredPlanIdGenerator(plan.plan_id))
        brief = service.prepare(
            PlanningRequest(
                "create",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                f"{key}:prepare",
            ),
            _WEB_MODEL,
        )
        review = require_proposal(
            service.handle(
                PlanningCommand(
                    _WEB_MODEL,
                    SubmitProposalDraft(
                        brief.run_id,
                        f"{key}:proposal",
                        brief.brief_context_digest,
                        proposal_draft_from_plan(plan),
                    ),
                ),
            )
        )
        response.status_code = 202
        return {"created": False, "proposal": proposal_payload(review, brief)}
    except HTTPException:
        raise
    except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
        _raise_lifecycle(exc)
    raise AssertionError("proposal preparation must return a review response")


@router.patch("/plans/{plan_id}")
def patch_plan(
    plan_id: str, request: Request, payload: Annotated[dict, Body()], response: Response
) -> dict:
    """Transition status or create/decide an exact structural revision proposal."""
    plan = _load_or_404(plan_id)

    if payload.get("proposal_id"):
        learner = require_browser_learner(request)
        allowed = {
            "proposal_id",
            "proposal_digest",
            "decision",
            "idempotency_key",
            "expected_document_digest",
            "expected_structure_digest",
            "expected_document_revision",
            "expected_structure_revision",
            "reason",
        }
        if set(payload) - allowed:
            raise HTTPException(
                status_code=400,
                detail="proposal decision cannot be mixed with structural or status fields",
            )
        try:
            service = planning_lifecycle(evidence=plan.evidence)
            review = require_proposal(service.inspect(ProposalRef(str(payload["proposal_id"]))))
            if review.mode != "revise":
                raise HTTPException(
                    status_code=409,
                    detail="PATCH /plans/{plan_id} can decide only a revision proposal",
                )
            if review.plan_preview.plan_id != plan_id:
                raise HTTPException(
                    status_code=409,
                    detail="revision proposal target does not match the route plan",
                )
            outcome = require_outcome(
                service.handle(
                    PlanningCommand(
                        learner,
                        DecideProposal(
                            str(payload["proposal_id"]),
                            str(payload.get("proposal_digest", "")),
                            _plan_decision(payload.get("decision")),
                            _request_key(payload, "web-revision-decision"),
                            reason=str(payload.get("reason", "")),
                            expected_document_digest=str(
                                payload.get("expected_document_digest", "")
                            ),
                            expected_structure_digest=str(
                                payload.get("expected_structure_digest", "")
                            ),
                            expected_document_revision=payload.get("expected_document_revision"),
                            expected_structure_revision=payload.get("expected_structure_revision"),
                        ),
                    ),
                )
            )
        except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
            _raise_lifecycle(exc)
        body = {"outcome": outcome_payload(outcome)}
        if outcome.status == "applied":
            body.update(_plan_response(plan_id))
        return body

    mutation_fields = set(payload) - {"idempotency_key"}
    if not mutation_fields:
        raise HTTPException(status_code=400, detail="patch contains no mutation")
    if mutation_fields == {"reason"}:
        raise HTTPException(status_code=400, detail="reason requires a status transition")
    outcome_fields = {"done", "outcome", "evidence_ids", "attest_reason", "confirmation"}
    if mutation_fields & outcome_fields:
        raise HTTPException(
            status_code=400,
            detail="milestone outcomes must use the milestone outcome endpoint",
        )
    structural_fields = mutation_fields - {"status", "reason"}
    if "status" in mutation_fields and structural_fields:
        raise HTTPException(
            status_code=400,
            detail="mixed structural and status changes are not allowed",
        )
    if "status" in mutation_fields:
        learner = require_browser_learner(request)
        status = str(payload["status"]).strip().lower()
        if status not in PLAN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
        try:
            outcome = require_outcome(
                planning_lifecycle(evidence=plan.evidence).handle(
                    PlanningCommand(
                        learner,
                        TransitionPlanStatus(
                            plan.plan_id,
                            status,
                            _request_key(payload, "web-status"),
                            reason=str(payload.get("reason", "")),
                        ),
                    ),
                )
            )
        except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
            _raise_lifecycle(exc)
        return {"outcome": outcome_payload(outcome), **_plan_response(plan_id)}

    supported_structural = {
        "markdown",
        "title",
        "topics",
        "target_date",
        "energy_floor",
        "review_cadence_days",
        "milestones",
    }
    unknown = structural_fields - supported_structural
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported structural patch fields: {sorted(unknown)}",
        )
    if "markdown" in structural_fields and len(structural_fields) != 1:
        raise HTTPException(
            status_code=400,
            detail="whole-Markdown revision cannot be mixed with individual structural fields",
        )

    if "markdown" in payload:
        try:
            replacement = parse_plan(str(payload["markdown"]), plan_id=plan.plan_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
        replacement.plan_id = plan.plan_id
        replacement.created = plan.created
        replacement.status = plan.status
        replacement.evidence = copy.deepcopy(plan.evidence)
        replacement.evidence_dispositions = copy.deepcopy(plan.evidence_dispositions)
        replacement.checkpoints = copy.deepcopy(plan.checkpoints)
        replacement.learning_records = copy.deepcopy(plan.learning_records)
        replacement.decisions = copy.deepcopy(plan.decisions)
        if replacement.notes != plan.notes:
            raise HTTPException(
                status_code=400,
                detail="top-level notes cannot be changed by the compatibility revision adapter",
            )
        candidate = replacement
    else:
        candidate = copy.deepcopy(plan)

    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        candidate.title = title
    if "topics" in payload:
        candidate.topics = [str(t).strip() for t in payload["topics"] if str(t).strip()]
    if "target_date" in payload:
        candidate.target_date = str(payload["target_date"]).strip()
    if "notes" in payload:
        candidate.notes = str(payload["notes"])
    for field_name, lo, hi in (("energy_floor", 1, 10), ("review_cadence_days", 1, 90)):
        if field_name in payload:
            try:
                value = int(payload[field_name])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"{field_name} must be an integer"
                ) from exc
            setattr(candidate, field_name, max(lo, min(hi, value)))

    if "milestones" in payload:
        from studyloop.planning.models import Milestone

        items = payload["milestones"]
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="milestones must be a list")
        if any(isinstance(item, dict) and item.get("done") is True for item in items):
            raise HTTPException(
                status_code=400,
                detail="structural milestone replacement cannot assert completion",
            )
        candidate.milestones = [
            Milestone(
                title=str(item.get("title", "")).strip() or "Untitled milestone",
                done=bool(item.get("done", False)),
                concepts=[str(c).strip() for c in (item.get("concepts") or []) if str(c).strip()],
                notes=str(item.get("notes", "")).strip(),
            )
            for item in items
            if isinstance(item, dict)
        ]

    key = _request_key(payload, "web-revision")
    try:
        service = planning_lifecycle(evidence=plan.evidence)
        brief = service.prepare(
            PlanningRequest(
                "revise",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                f"{key}:prepare",
                plan_id=plan.plan_id,
                evidence_ids=tuple(item.evidence_id for item in plan.evidence),
            ),
            _WEB_MODEL,
        )
        review = require_proposal(
            service.handle(
                PlanningCommand(
                    _WEB_MODEL,
                    SubmitProposalDraft(
                        brief.run_id,
                        f"{key}:proposal",
                        brief.brief_context_digest,
                        proposal_draft_from_plan(candidate, revise=True),
                    ),
                ),
            )
        )
    except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
        _raise_lifecycle(exc)
    response.status_code = 202
    return {"updated": False, "proposal": proposal_payload(review, brief)}


@router.post("/plans/{plan_id}/milestones/{index}/toggle")
def toggle_milestone(
    plan_id: str,
    index: int,
    request: Request,
    payload: Annotated[dict | None, Body()] = None,
) -> dict:
    """Compatibility path for an explicit evidence-backed milestone outcome."""
    plan = _load_or_404(plan_id)
    if index < 0 or index >= len(plan.milestones):
        raise HTTPException(status_code=404, detail=f"no milestone at index {index}")
    payload = payload or {}
    if not str(payload.get("outcome", "")).strip():
        raise HTTPException(
            status_code=400,
            detail="outcome is required; bare milestone toggles are forbidden",
        )
    outcome_kind = _milestone_outcome(payload.get("outcome"))
    if outcome_kind == "verified_complete":
        raise HTTPException(
            status_code=400,
            detail=(
                "browser learner requests may use only learner attestation; "
                "verified completion is recorded by the trusted internal recorder"
            ),
        )
    if "done" in payload:
        raise HTTPException(status_code=400, detail="done toggles are forbidden; use outcome")
    evidence_ids = tuple(str(item) for item in payload.get("evidence_ids", ()))
    learner = require_browser_learner(request)
    try:
        service = planning_lifecycle(evidence=plan.evidence)
        outcome = require_outcome(
            service.handle(
                PlanningCommand(
                    learner,
                    RecordMilestoneOutcome(
                        plan.plan_id,
                        plan.milestones[index].milestone_id,
                        outcome_kind,
                        evidence_ids,
                        _request_key(payload, "web-milestone"),
                        reason=str(payload.get("reason", "")),
                        confirmation=str(payload.get("confirmation", "")),
                    ),
                ),
            )
        )
    except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
        _raise_lifecycle(exc)
    return {"outcome": outcome_payload(outcome), "index": index, **_plan_response(plan_id)}


@router.delete("/plans/{plan_id}")
def remove_plan(plan_id: str, request: Request) -> dict:
    """Abandon a plan while retaining Markdown and audit history."""
    plan = _load_or_404(plan_id)
    learner = require_browser_learner(request)
    try:
        outcome = require_outcome(
            planning_lifecycle(evidence=plan.evidence).handle(
                PlanningCommand(
                    learner,
                    TransitionPlanStatus(
                        plan.plan_id,
                        "abandoned",
                        f"web-abandon:{uuid.uuid4().hex}",
                        reason="Learner abandoned plan through compatibility API",
                    ),
                ),
            )
        )
    except (LifecycleError, PlanningRepositoryError, InvalidPlanIdError) as exc:
        _raise_lifecycle(exc)
    return {
        "deleted": False,
        "abandoned": True,
        "outcome": outcome_payload(outcome),
        **_plan_response(plan_id),
    }
