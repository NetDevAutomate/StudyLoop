"""Thin HTTP adapters for durable agentic planning conversations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Literal, NoReturn, cast

from fastapi import APIRouter, Body, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from studyloop.planning.compat import require_proposal
from studyloop.planning.contracts import PlanningRequest, PlanningRunRef, ProposalRef
from studyloop.planning.conversation_contracts import (
    PRIVACY_NOTICE,
    ConversationConflictError,
    ConversationRefusedError,
    LearnerTurn,
    OutboxEvent,
    PrepareDecisionIntent,
)
from studyloop.planning.repository import PlanCapacityError, PlanConflictError, PlanningRef
from studyloop.web.learner_auth import browser_csrf_token, require_browser_learner

if TYPE_CHECKING:
    from studyloop.web.planning_services import PlanningServices

router = APIRouter()


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversationBody(_ClosedModel):
    mode: Literal["create", "revise"]
    plan_id: str = ""


class LearnerTurnBody(_ClosedModel):
    text: str = Field(min_length=1, max_length=40_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RetryBody(_ClosedModel):
    turn_id: str = Field(min_length=1, max_length=200)
    expected_turn_version: int = Field(ge=1)


class StopBody(_ClosedModel):
    pass


class DecisionBaseBody(_ClosedModel):
    document_digest: str = ""
    structure_digest: str = ""
    document_revision: int | None = None
    structure_revision: int | None = None


class DecisionBody(_ClosedModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    proposal_digest: str = Field(min_length=1, max_length=200)
    outcome: Literal["approve", "reject"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    base: DecisionBaseBody = Field(default_factory=DecisionBaseBody)


def _services(request: Request) -> PlanningServices:
    return request.app.state.planning_services


def _raise_planning(exc: Exception) -> NoReturn:
    if isinstance(exc, (ConversationConflictError, PlanCapacityError, PlanConflictError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ConversationRefusedError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _privacy() -> dict[str, object]:
    return {
        "text": PRIVACY_NOTICE,
        "local_recovery_state": True,
        "automatic_expiry": False,
        "configured_model_context": True,
    }


@router.post("/planning/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    body: Annotated[CreateConversationBody, Body()],
) -> dict[str, object]:
    require_browser_learner(request)
    services = _services(request)
    if body.mode == "create":
        if body.plan_id:
            raise HTTPException(status_code=400, detail="create conversation cannot name a plan")
        capacity = services.capacity()
        if not capacity["can_create"]:
            raise HTTPException(status_code=409, detail="maximum of 3 current plans reached")
    else:
        if not body.plan_id:
            raise HTTPException(status_code=400, detail="revise conversation requires plan_id")
        try:
            services.lifecycle.repository.inspect(PlanningRef(body.plan_id))
        except PlanConflictError as exc:
            _raise_planning(exc)
        capacity = services.capacity()
    conversation_id = f"conversation-{uuid.uuid4().hex}"
    services.store.create_conversation(conversation_id, body.mode, body.plan_id)
    return {
        "conversation_id": conversation_id,
        "mode": body.mode,
        "plan_id": body.plan_id,
        "phase": "ready",
        "privacy_notice": _privacy(),
        "capacity": capacity,
        "csrf_token": browser_csrf_token(request),
    }


@router.post("/planning/conversations/{conversation_id}/context")
async def attach_context(request: Request, conversation_id: str) -> dict[str, object]:
    require_browser_learner(request)
    services = _services(request)
    services.store.get_conversation(conversation_id)
    content_type = request.headers.get("content-type", "").casefold()
    if content_type.startswith("application/json"):
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"kind", "label", "content"}:
            raise HTTPException(status_code=422, detail="closed planning context schema required")
        if payload.get("kind") != "pasted":
            raise HTTPException(status_code=400, detail="JSON context kind must be pasted")
        label = str(payload.get("label", "pasted text"))
        content = str(payload.get("content", ""))
        media_type = "text/plain"
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        if set(form) - {"file", "label"} or "file" not in form:
            raise HTTPException(status_code=422, detail="closed planning upload schema required")
        upload = cast("UploadFile", form["file"])
        if not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="plain-text file is required")
        raw = await upload.read()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400, detail="planning upload must be UTF-8 text"
            ) from exc
        label = str(form.get("label") or getattr(upload, "filename", "selected text"))
        media_type = str(getattr(upload, "content_type", "text/plain"))
    else:
        raise HTTPException(status_code=415, detail="planning context must be JSON or multipart")
    try:
        ingested = services.context.ingest(
            conversation_id,
            label=label,
            content=content,
            media_type=media_type,
        )
    except (ConversationConflictError, ConversationRefusedError) as exc:
        _raise_planning(exc)
    return {
        "context_id": ingested.context_id,
        "label": ingested.label,
        "content_digest": ingested.content_digest,
        "size": ingested.size,
        "tier": ingested.tier,
    }


@router.post(
    "/planning/conversations/{conversation_id}/turns",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_turn(
    request: Request,
    conversation_id: str,
    body: Annotated[LearnerTurnBody, Body()],
) -> dict[str, object]:
    require_browser_learner(request)
    services = _services(request)
    conversation = services.store.get_conversation(conversation_id)
    if services.runtime is None:
        raise HTTPException(status_code=503, detail="planning model is not configured")
    if conversation.mode == "create" and not services.capacity()["can_create"]:
        raise HTTPException(status_code=409, detail="maximum of 3 current plans reached")
    turn_id = (
        "turn-"
        + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"studyloop:{conversation_id}:{body.idempotency_key}",
        ).hex
    )
    planning_request = PlanningRequest(
        conversation.mode,
        body.text,
        f"web-turn:{conversation_id}:{body.idempotency_key}",
        conversation.plan_id,
    )
    try:
        receipt = services.runtime.capture_turn(
            conversation_id,
            LearnerTurn(turn_id, body.text, planning_request),
        )
        if receipt.status == "ready":
            services.schedule_turn(receipt)
    except (ConversationConflictError, ConversationRefusedError, PlanCapacityError) as exc:
        _raise_planning(exc)
    return {
        "turn_id": turn_id,
        "status": "scheduled" if receipt.status == "ready" else receipt.status,
        "turn_version": receipt.turn_version,
    }


def _latest_proposal(services: PlanningServices, conversation_id: str) -> dict[str, object] | None:
    proposal_id = ""
    for event in services.store.replay_outbox(conversation_id, 0):
        if event.event_type != "capability_result":
            continue
        if event.payload.get("name") != "submit_plan_proposal":
            continue
        result = event.payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("proposal_id"), str):
            proposal_id = result["proposal_id"]
    if not proposal_id:
        return None
    review = require_proposal(services.lifecycle.inspect(ProposalRef(proposal_id)))
    brief = services.lifecycle.inspect(PlanningRunRef(review.run_id))
    return {
        "proposal_id": review.proposal_id,
        "proposal_digest": review.proposal_digest,
        "mode": review.mode,
        "title": review.plan_preview.title,
        "markdown": review.markdown_preview,
        "plan": review.plan_preview.summary(),
        "unknowns": [
            {"unknown_id": item.unknown_id, "question": item.question, "impact": item.impact}
            for item in review.plan_preview.unknowns
        ],
        "evidence_dispositions": [
            {
                "evidence_id": item.evidence_id,
                "disposition": item.disposition,
                "reason": item.reason,
            }
            for item in review.plan_preview.evidence_dispositions
        ],
        "base": {
            "document_digest": getattr(brief, "target_document_digest", ""),
            "structure_digest": getattr(brief, "target_structure_digest", ""),
            "document_revision": getattr(brief, "target_document_revision", None),
            "structure_revision": getattr(brief, "target_structure_revision", None),
        },
    }


@router.get("/planning/conversations/{conversation_id}")
def get_conversation(request: Request, conversation_id: str) -> dict[str, object]:
    services = _services(request)
    conversation = services.store.get_conversation(conversation_id)
    turns = services.store.list_turns(conversation_id)
    assistant_by_turn = {
        message.turn_id: message for message in services.store.list_messages(conversation_id)
    }
    messages: list[dict[str, object]] = []
    transcript_cursor = 0
    for turn in turns:
        assistant = assistant_by_turn.get(turn.turn_id)
        learner_sequence = (
            max(transcript_cursor, assistant.outbox_seq - 1)
            if assistant is not None
            else transcript_cursor
        )
        messages.append(
            {
                "role": "learner",
                "content": turn.learner_text,
                "sequence": learner_sequence,
            }
        )
        if assistant is not None:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant.content,
                    "sequence": assistant.outbox_seq,
                }
            )
            transcript_cursor = assistant.outbox_seq
    latest = turns[-1] if turns else None
    proposal = _latest_proposal(services, conversation_id)
    if proposal is not None:
        phase = "proposal"
    elif latest is None:
        phase = "ready"
    elif latest.status == "retryable":
        phase = "retryable"
    elif latest.status in {"ready", "attempt_active"}:
        phase = "thinking"
    else:
        phase = "conversation"
    return {
        "conversation_id": conversation.conversation_id,
        "mode": conversation.mode,
        "plan_id": conversation.plan_id,
        "phase": phase,
        "capacity": services.capacity(),
        "messages": messages,
        "latest_turn": (
            {
                "turn_id": latest.turn_id,
                "status": latest.status,
                "turn_version": latest.turn_version,
            }
            if latest is not None
            else None
        ),
        "proposal": proposal,
        "events_url": f"/api/planning/conversations/{conversation_id}/events",
    }


@router.post("/planning/conversations/{conversation_id}/retry", status_code=202)
async def retry_turn(
    request: Request,
    conversation_id: str,
    body: Annotated[RetryBody, Body()],
) -> dict[str, object]:
    require_browser_learner(request)
    services = _services(request)
    services.store.get_conversation(conversation_id)
    if services.runtime is None:
        raise HTTPException(status_code=503, detail="planning model is not configured")
    turn = services.store.get_turn(conversation_id, body.turn_id)
    attempts = services.store.list_attempts(body.turn_id)
    if (
        turn.turn_version != body.expected_turn_version
        or turn.status != "retryable"
        or not attempts
        or attempts[-1].status != "interrupted"
    ):
        raise HTTPException(
            status_code=409,
            detail="retry requires the exact interrupted learner turn version",
        )
    services.schedule_retry(conversation_id, body.turn_id, body.expected_turn_version)
    return {"turn_id": body.turn_id, "status": "scheduled"}


@router.post("/planning/conversations/{conversation_id}/stop")
async def stop_turn(
    request: Request,
    conversation_id: str,
    _body: Annotated[StopBody, Body()],
) -> dict[str, object]:
    require_browser_learner(request)
    services = _services(request)
    services.store.get_conversation(conversation_id)
    stopped = await services.stop(conversation_id)
    return {"stopped": stopped}


@router.post("/planning/proposals/{proposal_id}/decision")
def decide_proposal(
    request: Request,
    proposal_id: str,
    body: Annotated[DecisionBody, Body()],
) -> dict[str, object]:
    actor = require_browser_learner(request)
    services = _services(request)
    command = PrepareDecisionIntent(
        body.conversation_id,
        proposal_id,
        body.proposal_digest,
        body.base.document_digest,
        body.base.structure_digest,
        body.outcome,
        f"web-decision:{proposal_id}:{body.idempotency_key}",
        body.base.document_revision,
        body.base.structure_revision,
    )
    try:
        intent = services.decisions.prepare_intent(command)
        projected = services.decisions.decide(intent.intent_id, actor)
    except Exception as exc:
        if isinstance(
            exc, (ConversationConflictError, ConversationRefusedError, PlanConflictError)
        ):
            _raise_planning(exc)
        raise
    outcome = dict(projected.payload)
    return {
        "intent_id": projected.intent_id,
        "status": projected.status,
        "outcome": outcome.get("status", ""),
        "plan_id": outcome.get("plan_id", ""),
    }


def safe_event(event: OutboxEvent) -> dict[str, object]:
    """Project durable outbox history without exposing capability payloads."""
    sequence = int(event.sequence)
    event_type = str(event.event_type)
    payload = event.payload
    data: dict[str, object]
    if event_type == "assistant_message":
        data = {key: payload[key] for key in ("message_id", "turn_id", "content")}
    elif event_type == "attempt_interrupted":
        data = {"turn_id": payload.get("turn_id", ""), "retryable": True}
    elif event_type == "capability_result":
        name = payload.get("name", "")
        data = {"name": name, "status": payload.get("status", "")}
        result = payload.get("result")
        if name == "submit_plan_proposal" and isinstance(result, dict):
            data["proposal_id"] = result.get("proposal_id", "")
            event_type = "proposal_ready"
    elif event_type == "decision_result":
        data = {
            key: payload.get(key, "") for key in ("status", "plan_id", "proposal_id", "message")
        }
    else:
        data = {"status": "updated"}
    return {"sequence": sequence, "type": event_type, "data": data}


__all__ = ["router", "safe_event"]
