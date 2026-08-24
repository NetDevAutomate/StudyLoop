"""Journal projection and typed payload rehydration for planning lifecycle state."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from typing import TYPE_CHECKING, Any, cast

from .contracts import (
    FoldedPlanningState,
    PersistedProposal,
    PlanningBrief,
    PlanOutcome,
    ProposalConflictError,
    ProposalReview,
    SourceReference,
)
from .models import (
    Checkpoint,
    ConceptRef,
    ConceptRelation,
    DecisionRecord,
    EvidenceDisposition,
    EvidenceRef,
    Goal,
    LearningRecord,
    Milestone,
    Mission,
    PlanUnknown,
    Resource,
    StudyPlan,
)

if TYPE_CHECKING:
    from .journal import JournalEvent
    from .repository import PlanningRepository

_OUTCOME_STATUSES = frozenset(
    {
        "applied",
        "rejected",
        "recorded",
        "verified_complete",
        "learner_attested",
        "incomplete",
        "transitioned",
        "imported",
    }
)


def canonical_lifecycle_digest(domain: str, payload: object) -> str:
    """Hash versioned canonical JSON in one lifecycle-specific domain."""
    envelope = {"domain": domain, "version": 1, "payload": payload}
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:v1:{sha256(encoded).hexdigest()}"


def brief_payload(brief: PlanningBrief, *, include_raw: bool) -> dict[str, object]:
    """Serialize a brief while allowing raw private input to stay out of JSONL."""
    payload = asdict(brief)
    if not include_raw:
        payload["raw_brain_dump"] = ""
    return payload


def persisted_proposal_payload(proposal: PersistedProposal) -> dict[str, object]:
    """Return a JSON-safe authoritative proposal projection."""
    return asdict(proposal)


class LifecycleJournalProjection:
    """Fold validated repository events into restart-safe lifecycle state."""

    def __init__(self, repository: PlanningRepository) -> None:
        self.repository = repository

    def fold(self, events: tuple[JournalEvent, ...]) -> FoldedPlanningState:
        briefs: dict[str, PlanningBrief] = {}
        proposals: dict[str, PersistedProposal] = {}
        latest: dict[str, str] = {}
        decisions: dict[str, PlanOutcome] = {}
        request_keys: dict[tuple[str, str], tuple[str, str]] = {}
        proposal_keys: dict[tuple[str, str], tuple[str, str]] = {}
        decision_keys: dict[tuple[str, str], tuple[str, PlanOutcome]] = {}
        command_keys: dict[tuple[str, str], tuple[str, PlanOutcome]] = {}
        overrides: dict[str, tuple[str, ...]] = {}
        for event in events:
            terminal_after = event.event == "committed" or (
                event.event == "recovered" and event.recovery.get("classification") == "after"
            )
            if not terminal_after:
                continue
            lifecycle = event.payload.get("lifecycle")
            if not isinstance(lifecycle, dict):
                continue
            event_type = lifecycle.get("type")
            if event_type == "run_captured":
                payload = lifecycle.get("brief")
                if not isinstance(payload, dict):
                    continue
                run_id = str(payload.get("run_id", ""))
                raw = self._read_brain_dump(
                    run_id,
                    str(lifecycle.get("brain_dump_artifact", "")),
                    str(lifecycle.get("brain_dump_digest", "")),
                )
                brief = _brief_from_payload(payload, raw)
                briefs[brief.run_id] = brief
                request_keys[(str(lifecycle["actor_id"]), str(lifecycle["request_key"]))] = (
                    str(lifecycle["request_digest"]),
                    brief.run_id,
                )
            elif event_type == "proposal_issued":
                payload = self._read_proposal_payload(
                    str(lifecycle.get("run_id", "")),
                    str(lifecycle.get("proposal_id", "")),
                    str(lifecycle.get("proposal_artifact", "")),
                    str(lifecycle.get("artifact_digest", "")),
                )
                proposal = _persisted_proposal_from_payload(payload)
                proposals[proposal.review.proposal_id] = proposal
                latest[proposal.review.run_id] = proposal.review.proposal_id
                proposal_keys[(str(lifecycle["actor_id"]), str(lifecycle["command_key"]))] = (
                    str(lifecycle["input_digest"]),
                    proposal.review.proposal_id,
                )
            elif event_type == "proposal_decided":
                outcome_payload = lifecycle.get("outcome")
                if not isinstance(outcome_payload, dict):
                    continue
                outcome = _outcome_from_event(outcome_payload, event, applied_only=True)
                proposal_id = str(lifecycle["proposal_id"])
                decisions[proposal_id] = outcome
                decision_keys[(str(lifecycle["actor_id"]), str(lifecycle["command_key"]))] = (
                    str(lifecycle["input_digest"]),
                    outcome,
                )
                raw_ids = lifecycle.get("active_goal_ids", [])
                if outcome.goal_limit_override_digest and isinstance(raw_ids, list):
                    overrides[outcome.goal_limit_override_digest] = tuple(
                        str(item) for item in raw_ids
                    )
            elif all(
                key in lifecycle for key in ("actor_id", "command_key", "input_digest", "outcome")
            ):
                outcome_payload = lifecycle.get("outcome")
                if not isinstance(outcome_payload, dict):
                    continue
                outcome = _outcome_from_event(outcome_payload, event, applied_only=False)
                command_keys[(str(lifecycle["actor_id"]), str(lifecycle["command_key"]))] = (
                    str(lifecycle["input_digest"]),
                    outcome,
                )
        return FoldedPlanningState(
            briefs_by_run=briefs,
            proposals_by_id=proposals,
            latest_proposal_by_run=latest,
            decisions_by_proposal=decisions,
            request_keys=request_keys,
            proposal_keys=proposal_keys,
            decision_keys=decision_keys,
            command_keys=command_keys,
            valid_goal_overrides=overrides,
        )

    def _read_proposal_payload(
        self,
        run_id: str,
        proposal_id: str,
        artifact: str,
        expected_digest: str,
    ) -> dict[str, object]:
        if not run_id or not proposal_id or artifact != f"{proposal_id}.json":
            raise ProposalConflictError("issued proposal has an invalid private artifact reference")
        path = self.repository.paths.private_runs / run_id / artifact
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProposalConflictError("issued proposal artifact is unavailable") from error
        actual = canonical_lifecycle_digest("studyloop.private-proposal", {"content_exact": raw})
        if actual != expected_digest:
            raise ProposalConflictError("issued proposal artifact digest mismatch")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProposalConflictError("issued proposal artifact is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ProposalConflictError("issued proposal artifact must be a JSON object")
        return {str(key): value for key, value in payload.items()}

    def _read_brain_dump(self, run_id: str, artifact: str, expected_digest: str) -> str:
        if not run_id or artifact != "brain-dump.txt":
            raise ProposalConflictError("captured run has an invalid private artifact reference")
        path = self.repository.paths.private_runs / run_id / artifact
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProposalConflictError("captured brain dump artifact is unavailable") from error
        actual = canonical_lifecycle_digest("studyloop.private-brain-dump", {"content_exact": raw})
        if actual != expected_digest:
            raise ProposalConflictError("captured brain dump artifact digest mismatch")
        return raw


def _outcome_from_event(
    payload: dict[str, object],
    event: JournalEvent,
    *,
    applied_only: bool,
) -> PlanOutcome:
    result = dict(payload)
    if not applied_only or result.get("status") == "applied":
        result.update(
            {
                "document_digest": event.result.get("document_digest") or "",
                "structure_digest": event.result.get("structure_digest") or "",
                "document_revision": event.result.get("document_revision"),
                "structure_revision": event.result.get("structure_revision"),
            }
        )
    status = str(result.get("status", ""))
    if status not in _OUTCOME_STATUSES:
        raise ProposalConflictError(f"journal contains unsupported plan outcome {status!r}")
    return PlanOutcome(
        status=cast("Any", status),
        plan_id=str(result.get("plan_id", "")),
        proposal_id=str(result.get("proposal_id", "")),
        document_digest=str(result.get("document_digest", "")),
        structure_digest=str(result.get("structure_digest", "")),
        document_revision=_optional_int(result.get("document_revision")),
        structure_revision=_optional_int(result.get("structure_revision")),
        goal_limit_override_digest=str(result.get("goal_limit_override_digest", "")),
        message=str(result.get("message", "")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProposalConflictError("journal field expected an integer or null")
    return value


def _required_int(value: object) -> int:
    result = _optional_int(value)
    if result is None:
        raise ProposalConflictError("journal field expected an integer")
    return result


def _brief_from_payload(payload: dict[str, object], raw: str) -> PlanningBrief:
    evidence = tuple(
        EvidenceRef(**item) for item in cast("list[dict[str, Any]]", payload["evidence"])
    )
    sources = tuple(
        SourceReference(**item)
        for item in cast("list[dict[str, Any]]", payload["source_references"])
    )
    return PlanningBrief(
        schema_version=_required_int(payload["schema_version"]),
        policy_version=_required_int(payload["policy_version"]),
        run_id=str(payload["run_id"]),
        mode=cast("Any", payload["mode"]),
        raw_brain_dump=raw,
        request_digest=str(payload["request_digest"]),
        brief_context_digest=str(payload["brief_context_digest"]),
        plan_id=str(payload["plan_id"]),
        target_document_digest=str(payload["target_document_digest"]),
        target_structure_digest=str(payload["target_structure_digest"]),
        target_document_revision=cast("int | None", payload["target_document_revision"]),
        target_structure_revision=cast("int | None", payload["target_structure_revision"]),
        target_plan=(
            _study_plan_from_dict(cast("dict[str, Any]", payload["target_plan"]))
            if payload.get("target_plan")
            else None
        ),
        current_count=_required_int(payload["current_count"]),
        max_current=_required_int(payload["max_current"]),
        active_goal_ids=tuple(cast("list[str]", payload["active_goal_ids"])),
        active_goal_set_digest=str(payload["active_goal_set_digest"]),
        evidence=evidence,
        source_references=sources,
        known_resources=tuple(
            Resource(**item)
            for item in cast("list[dict[str, Any]]", payload.get("known_resources", []))
        ),
        configured_topics=tuple(cast("list[str]", payload.get("configured_topics", []))),
        unresolved_gaps=tuple(cast("list[str]", payload.get("unresolved_gaps", []))),
        invariants=tuple(cast("list[str]", payload.get("invariants", []))),
        created_at=str(payload["created_at"]),
    )


def _persisted_proposal_from_payload(payload: dict[str, object]) -> PersistedProposal:
    review_payload = cast("dict[str, Any]", payload["review"])
    plan = _study_plan_from_dict(cast("dict[str, Any]", review_payload["plan_preview"]))
    review = ProposalReview(
        proposal_id=str(review_payload["proposal_id"]),
        run_id=str(review_payload["run_id"]),
        proposal_digest=str(review_payload["proposal_digest"]),
        brief_context_digest=str(review_payload["brief_context_digest"]),
        mode=cast("Any", review_payload["mode"]),
        plan_preview=plan,
        markdown_preview=str(review_payload["markdown_preview"]),
        alias_mapping=tuple(tuple(item) for item in review_payload["alias_mapping"]),
        resulting_active_goal_ids=tuple(review_payload["resulting_active_goal_ids"]),
        resulting_active_goal_set_digest=str(review_payload["resulting_active_goal_set_digest"]),
        validation_blockers=tuple(review_payload.get("validation_blockers", [])),
        nudges=tuple(review_payload.get("nudges", [])),
        supersedes_proposal_id=str(review_payload.get("supersedes_proposal_id", "")),
        created_at=str(review_payload.get("created_at", "")),
    )
    return PersistedProposal(
        review=review,
        base_document_digest=str(payload.get("base_document_digest", "")),
        base_structure_digest=str(payload.get("base_structure_digest", "")),
        base_document_revision=cast("int | None", payload.get("base_document_revision")),
        base_structure_revision=cast("int | None", payload.get("base_structure_revision")),
        requested_status=str(payload.get("requested_status", "draft")),
        evidence_dispositions=tuple(
            EvidenceDisposition(**item)
            for item in cast("list[dict[str, Any]]", payload.get("evidence_dispositions", []))
        ),
        explicit_relations=tuple(
            ConceptRelation(**item)
            for item in cast("list[dict[str, Any]]", payload.get("explicit_relations", []))
        ),
        next_action=str(payload.get("next_action", "")),
        goal_limit_override_requested=bool(payload.get("goal_limit_override_requested", False)),
        goal_limit_override_reason=str(payload.get("goal_limit_override_reason", "")),
    )


def _study_plan_from_dict(payload: dict[str, Any]) -> StudyPlan:
    """Rehydrate the complete proposal projection without trusting Markdown."""
    return StudyPlan(
        plan_id=payload["plan_id"],
        title=payload["title"],
        status=payload["status"],
        created=payload["created"],
        updated=payload["updated"],
        topics=list(payload["topics"]),
        energy_floor=payload["energy_floor"],
        target_date=payload["target_date"],
        review_cadence_days=payload["review_cadence_days"],
        mission=Mission(**payload["mission"]),
        next_action=str(payload.get("next_action", "")),
        milestones=[Milestone(**item) for item in payload["milestones"]],
        learning_records=[LearningRecord(**item) for item in payload["learning_records"]],
        resources=[Resource(**item) for item in payload["resources"]],
        checkpoints=[Checkpoint(**item) for item in payload["checkpoints"]],
        notes=payload["notes"],
        schema_version=payload["schema_version"],
        document_revision=payload["document_revision"],
        structure_revision=payload["structure_revision"],
        document_digest=payload["document_digest"],
        structure_digest=payload["structure_digest"],
        brief_context_digest=payload["brief_context_digest"],
        goals=[Goal(**item) for item in payload["goals"]],
        evidence=[EvidenceRef(**item) for item in payload["evidence"]],
        evidence_dispositions=[
            EvidenceDisposition(**item) for item in payload["evidence_dispositions"]
        ],
        concepts=[ConceptRef(**item) for item in payload["concepts"]],
        concept_relations=[ConceptRelation(**item) for item in payload["concept_relations"]],
        unknowns=[PlanUnknown(**item) for item in payload["unknowns"]],
        decisions=[DecisionRecord(**item) for item in payload["decisions"]],
    )
