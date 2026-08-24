"""Closed, pre-bound capability catalogue for the confined planning model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlsplit

from .contracts import (
    ActorContext,
    ConceptProposal,
    ConceptRelationProposal,
    GoalProposal,
    MilestoneProposal,
    PlanningCommand,
    PlanningRequest,
    PlanProposalDraft,
    ProposalRef,
    SubmitProposalDraft,
)
from .lifecycle_journal import canonical_lifecycle_digest
from .models import EvidenceDisposition, Mission, PlanUnknown, Resource


class CapabilityRefusedError(ValueError):
    """A model call is outside the immutable planning capability contract."""


class PlanningCapabilityName(StrEnum):
    PREPARE_PLAN = "prepare_plan"
    SUBMIT_PLAN_PROPOSAL = "submit_plan_proposal"
    GET_PLAN_PROPOSAL = "get_plan_proposal"


type FrozenJson = (
    str | int | float | bool | None | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)


def _freeze(value: Any) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported schema value {type(value).__name__}")


def _thaw(value: FrozenJson) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _freeze_mapping(value: dict[str, object]) -> Mapping[str, FrozenJson]:
    frozen = _freeze(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - input is a mapping
        raise TypeError("frozen schema is not a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class PlanningCapabilitySchema:
    name: PlanningCapabilityName
    description: str
    input_schema: Mapping[str, FrozenJson]

    def to_wire(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name.value,
                "description": self.description,
                "parameters": _thaw(self.input_schema),
            },
        }


_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_MISSION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["why", "success"],
    "properties": {
        "why": {"type": "string"},
        "success": _STRING_ARRAY,
        "constraints": _STRING_ARRAY,
        "out_of_scope": _STRING_ARRAY,
    },
}
_GOAL = {
    "type": "object",
    "additionalProperties": False,
    "required": ["alias", "title", "reason", "alignment_rationale"],
    "properties": {
        "alias": {"type": "string"},
        "title": {"type": "string"},
        "reason": {"type": "string"},
        "alignment_rationale": {"type": "string"},
        "status": {"type": "string", "enum": ["active", "paused", "complete"]},
        "existing_goal_id": {"type": "string"},
    },
}
_MILESTONE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["alias", "goal_alias", "title"],
    "properties": {
        "alias": {"type": "string"},
        "goal_alias": {"type": "string"},
        "title": {"type": "string"},
        "notes": {"type": "string"},
        "concept_aliases": _STRING_ARRAY,
        "existing_milestone_id": {"type": "string"},
    },
}
_RESOURCE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label"],
    "properties": {
        "label": {"type": "string"},
        "url": {
            "type": "string",
            "description": "Inert HTTP(S) citation; never fetched by StudyLoop",
            "maxLength": 2048,
        },
        "note": {"type": "string"},
    },
}
_DRAFT = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "mission",
        "goals",
        "milestones",
        "evidence_dispositions",
        "next_action",
    ],
    "properties": {
        "title": {"type": "string"},
        "mission": _MISSION,
        "goals": {"type": "array", "maxItems": 3, "items": _GOAL},
        "milestones": {"type": "array", "items": _MILESTONE},
        "topics": _STRING_ARRAY,
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["alias", "display_label"],
                "properties": {
                    "alias": {"type": "string"},
                    "display_label": {"type": "string"},
                    "existing_concept_id": {"type": "string"},
                },
            },
        },
        "concept_relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_alias", "target_alias", "relation", "reason", "provenance"],
                "properties": {
                    "source_alias": {"type": "string"},
                    "target_alias": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": ["equivalent", "broader", "narrower", "related", "distinct"],
                    },
                    "reason": {"type": "string"},
                    "provenance": {"type": "string"},
                },
            },
        },
        "evidence_dispositions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["evidence_id", "disposition", "reason"],
                "properties": {
                    "evidence_id": {"type": "string"},
                    "disposition": {
                        "type": "string",
                        "enum": ["selected", "rejected", "unresolved"],
                    },
                    "reason": {"type": "string"},
                },
            },
        },
        "resources": {"type": "array", "items": _RESOURCE},
        "unknowns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["unknown_id", "question", "impact"],
                "properties": {
                    "unknown_id": {"type": "string"},
                    "question": {"type": "string"},
                    "impact": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "resolved"]},
                },
            },
        },
        "next_action": {"type": "string"},
        "requested_status": {"type": "string", "enum": ["draft"]},
        "target_date": {"type": "string"},
        "energy_floor": {"type": "integer", "minimum": 1, "maximum": 10},
        "review_cadence_days": {"type": "integer", "minimum": 1},
        "goal_limit_override_requested": {"type": "boolean"},
        "goal_limit_override_reason": {"type": "string"},
    },
}


PLANNING_CAPABILITY_SCHEMAS: tuple[PlanningCapabilitySchema, ...] = (
    PlanningCapabilitySchema(
        PlanningCapabilityName.PREPARE_PLAN,
        "Prepare the server-bound learner brain dump and return its lifecycle brief.",
        _freeze_mapping({"type": "object", "additionalProperties": False, "properties": {}}),
    ),
    PlanningCapabilitySchema(
        PlanningCapabilityName.SUBMIT_PLAN_PROPOSAL,
        "Submit a typed proposal for learner review; this never approves it.",
        _freeze_mapping(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "brief_context_digest", "draft"],
                "properties": {
                    "run_id": {"type": "string"},
                    "brief_context_digest": {"type": "string"},
                    "draft": _DRAFT,
                },
            }
        ),
    ),
    PlanningCapabilitySchema(
        PlanningCapabilityName.GET_PLAN_PROPOSAL,
        "Inspect one proposal from the current bound planning run.",
        _freeze_mapping(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "proposal_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "proposal_id": {"type": "string"},
                },
            }
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class PlanningCapabilityCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]
    lifecycle_idempotency_key: str = ""


def normalize_planning_capability_call(
    call: PlanningCapabilityCall,
    *,
    expected_run_id: str = "",
) -> PlanningCapabilityCall:
    """Validate and detach one provider call before any durable side effect.

    This deliberately exercises the same hand-written decoder as dispatch.  A
    caller can therefore commit the normalized JSON intent before allowing the
    lifecycle to observe it, while unknown tools and authority-shaped extras
    still leave no durable capability record.
    """
    if not call.call_id.strip():
        raise CapabilityRefusedError("capability call ID is required")
    try:
        name = PlanningCapabilityName(call.name)
    except ValueError as exc:
        raise CapabilityRefusedError(f"unsupported planning capability {call.name!r}") from exc
    arguments = _mapping(call.arguments, "capability arguments")
    if name is PlanningCapabilityName.PREPARE_PLAN:
        if expected_run_id:
            raise CapabilityRefusedError("planning run is already prepared for this turn")
        _exact_keys(arguments, required=(), optional=(), label=name.value)
    elif name is PlanningCapabilityName.SUBMIT_PLAN_PROPOSAL:
        _exact_keys(
            arguments,
            required=("run_id", "brief_context_digest", "draft"),
            optional=(),
            label=name.value,
        )
        run_id = _string(arguments.get("run_id"), "run_id")
        if expected_run_id and run_id != expected_run_id:
            raise CapabilityRefusedError("capability run ID does not match the bound planning run")
        _string(arguments.get("brief_context_digest"), "brief_context_digest")
        _decode_draft(arguments.get("draft"))
    elif name is PlanningCapabilityName.GET_PLAN_PROPOSAL:
        _exact_keys(
            arguments,
            required=("run_id", "proposal_id"),
            optional=(),
            label=name.value,
        )
        run_id = _string(arguments.get("run_id"), "run_id")
        if expected_run_id and run_id != expected_run_id:
            raise CapabilityRefusedError("capability run ID does not match the bound planning run")
        _string(arguments.get("proposal_id"), "proposal_id")
    normalized = _thaw(_freeze(dict(arguments)))
    if not isinstance(normalized, dict):  # pragma: no cover - arguments are a mapping
        raise TypeError("normalized capability arguments are not an object")
    return PlanningCapabilityCall(call.call_id, name.value, normalized)


@dataclass(frozen=True, slots=True)
class PlanningCapabilityScope:
    """Server-owned durable identity for one provider attempt's capability calls."""

    conversation_id: str
    turn_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("conversation_id", self.conversation_id),
            ("turn_id", self.turn_id),
            ("attempt_id", self.attempt_id),
        ):
            if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
                raise ValueError(f"planning capability {label} is invalid")

    def lifecycle_idempotency_key(self, *, run_id: str, tool_call_id: str) -> str:
        """Derive the key Task 7 persists beside the complete original call tuple."""
        return "capability:" + canonical_lifecycle_digest(
            "studyloop.planning-capability-call",
            {
                "conversation_id": self.conversation_id,
                "turn_id": self.turn_id,
                "attempt_id": self.attempt_id,
                "run_id": run_id,
                "tool_call_id": tool_call_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PlanningCapabilityResult:
    call_id: str
    name: PlanningCapabilityName
    status: str
    payload: Mapping[str, FrozenJson]


class _LifecyclePort(Protocol):
    def prepare(self, request: PlanningRequest, actor: ActorContext) -> object: ...

    def handle(self, command: PlanningCommand) -> object: ...

    def inspect(self, ref: ProposalRef) -> object: ...


_MODEL_ACTOR = ActorContext("model", "planning-conversation-runtime", "confined-model")
_MISSING = object()


class PlanningCapabilityDispatcher:
    """Deep module: exact schema validation plus three lifecycle operations."""

    def __init__(
        self,
        lifecycle: _LifecyclePort,
        request: PlanningRequest,
        *,
        scope: PlanningCapabilityScope,
        expected_run_id: str = "",
    ) -> None:
        self._lifecycle = lifecycle
        self._request = request
        self._scope = scope
        self._run_id = expected_run_id

    def execute(self, call: PlanningCapabilityCall) -> PlanningCapabilityResult:
        if not call.call_id.strip():
            raise CapabilityRefusedError("capability call ID is required")
        try:
            name = PlanningCapabilityName(call.name)
        except ValueError as exc:
            raise CapabilityRefusedError(f"unsupported planning capability {call.name!r}") from exc
        arguments = _mapping(call.arguments, "capability arguments")

        if name is PlanningCapabilityName.PREPARE_PLAN:
            _exact_keys(arguments, required=(), optional=(), label=name.value)
            lifecycle_key = self._bound_lifecycle_key(call, run_id="")
            result = self._lifecycle.prepare(
                replace(self._request, idempotency_key=lifecycle_key),
                _MODEL_ACTOR,
            )
            run_id = str(getattr(result, "run_id", ""))
            if not run_id or (self._run_id and self._run_id != run_id):
                raise CapabilityRefusedError("prepared run does not match the bound planning run")
            self._run_id = run_id
            return _result(call, name, result)

        run_id = _string(arguments.get("run_id"), "run_id")
        if not self._run_id or run_id != self._run_id:
            raise CapabilityRefusedError("capability run ID does not match the bound planning run")

        if name is PlanningCapabilityName.SUBMIT_PLAN_PROPOSAL:
            _exact_keys(
                arguments,
                required=("run_id", "brief_context_digest", "draft"),
                optional=(),
                label=name.value,
            )
            command = SubmitProposalDraft(
                run_id=run_id,
                idempotency_key=self._bound_lifecycle_key(call, run_id=run_id),
                brief_context_digest=_string(
                    arguments.get("brief_context_digest"), "brief_context_digest"
                ),
                draft=_decode_draft(arguments.get("draft")),
            )
            return _result(
                call,
                name,
                self._lifecycle.handle(PlanningCommand(_MODEL_ACTOR, command)),
            )

        if name is PlanningCapabilityName.GET_PLAN_PROPOSAL:
            _exact_keys(
                arguments,
                required=("run_id", "proposal_id"),
                optional=(),
                label=name.value,
            )
            self._bound_lifecycle_key(call, run_id=run_id)
            result = self._lifecycle.inspect(
                ProposalRef(_string(arguments.get("proposal_id"), "proposal_id"))
            )
            if str(getattr(result, "run_id", "")) != self._run_id:
                raise CapabilityRefusedError("proposal does not belong to the bound planning run")
            return _result(call, name, result)

        raise CapabilityRefusedError(f"unsupported planning capability {name.value!r}")

    def _bound_lifecycle_key(self, call: PlanningCapabilityCall, *, run_id: str) -> str:
        expected = self._scope.lifecycle_idempotency_key(
            run_id=run_id,
            tool_call_id=call.call_id,
        )
        if call.lifecycle_idempotency_key and call.lifecycle_idempotency_key != expected:
            raise CapabilityRefusedError(
                "persisted capability idempotency key does not match its original scope"
            )
        return expected


def _result(
    call: PlanningCapabilityCall,
    name: PlanningCapabilityName,
    value: object,
) -> PlanningCapabilityResult:
    if is_dataclass(value) and not isinstance(value, type):
        payload = asdict(value)
    elif isinstance(value, dict):
        payload = value
    else:
        payload = {"value": str(value)}
    frozen = _freeze(payload)
    if not isinstance(frozen, Mapping):  # pragma: no cover - payload is always a mapping
        raise TypeError("capability result payload is not a mapping")
    return PlanningCapabilityResult(call.call_id, name, "ok", frozen)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CapabilityRefusedError(f"{label} must be an object with string keys")
    return value


def _exact_keys(
    value: Mapping[str, object],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    label: str,
) -> None:
    keys = set(value)
    missing = set(required) - keys
    extra = keys - set(required) - set(optional)
    if missing or extra:
        raise CapabilityRefusedError(
            f"{label} arguments do not match the closed schema; "
            f"missing={sorted(missing)}, unexpected={sorted(extra)}"
        )


def _string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise CapabilityRefusedError(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if value is _MISSING:
        return ()
    if not isinstance(value, list):
        raise CapabilityRefusedError(f"{label} must be an array of strings")
    return tuple(_string(item, label) for item in value)


def _objects(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if value is _MISSING:
        return ()
    if not isinstance(value, list):
        raise CapabilityRefusedError(f"{label} must be an array")
    return tuple(_mapping(item, label) for item in value)


def _integer(value: object, label: str, default: int) -> int:
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapabilityRefusedError(f"{label} must be an integer")
    return value


def _bounded_integer(
    value: object,
    label: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    result = _integer(value, label, default)
    if result < minimum or (maximum is not None and result > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise CapabilityRefusedError(f"{label} must be {limit}")
    return result


def _enum_string(value: object, label: str, allowed: frozenset[str]) -> str:
    result = _string(value, label)
    if result not in allowed:
        raise CapabilityRefusedError(f"{label} has an unsupported value")
    return result


def _boolean(value: object, label: str, default: bool = False) -> bool:
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise CapabilityRefusedError(f"{label} must be a boolean")
    return value


def _decode_draft(value: object) -> PlanProposalDraft:
    raw = _mapping(value, "draft")
    _exact_keys(
        raw,
        required=(
            "title",
            "mission",
            "goals",
            "milestones",
            "evidence_dispositions",
            "next_action",
        ),
        optional=(
            "topics",
            "concepts",
            "concept_relations",
            "resources",
            "unknowns",
            "requested_status",
            "target_date",
            "energy_floor",
            "review_cadence_days",
            "goal_limit_override_requested",
            "goal_limit_override_reason",
        ),
        label="draft",
    )
    mission_raw = _mapping(raw.get("mission"), "mission")
    _exact_keys(
        mission_raw,
        required=("why", "success"),
        optional=("constraints", "out_of_scope"),
        label="mission",
    )
    mission = Mission(
        why=_string(mission_raw.get("why"), "mission.why"),
        success=list(_strings(mission_raw.get("success"), "mission.success")),
        constraints=list(_strings(mission_raw.get("constraints", _MISSING), "mission.constraints")),
        out_of_scope=list(
            _strings(mission_raw.get("out_of_scope", _MISSING), "mission.out_of_scope")
        ),
    )

    goals: list[GoalProposal] = []
    for item in _objects(raw.get("goals"), "goals"):
        _exact_keys(
            item,
            required=("alias", "title", "reason", "alignment_rationale"),
            optional=("status", "existing_goal_id"),
            label="goal",
        )
        goals.append(
            GoalProposal(
                _string(item.get("alias"), "goal.alias"),
                _string(item.get("title"), "goal.title"),
                _string(item.get("reason"), "goal.reason"),
                _string(item.get("alignment_rationale"), "goal.alignment_rationale"),
                _enum_string(
                    item.get("status", "active"),
                    "goal.status",
                    frozenset({"active", "paused", "complete"}),
                ),
                _string(item.get("existing_goal_id", ""), "existing_goal_id", allow_empty=True),
            )
        )
    if len(goals) > 3:
        raise CapabilityRefusedError("proposal has more than three goals")

    milestones: list[MilestoneProposal] = []
    for item in _objects(raw.get("milestones"), "milestones"):
        _exact_keys(
            item,
            required=("alias", "goal_alias", "title"),
            optional=("notes", "concept_aliases", "existing_milestone_id"),
            label="milestone",
        )
        milestones.append(
            MilestoneProposal(
                _string(item.get("alias"), "milestone.alias"),
                _string(item.get("goal_alias"), "milestone.goal_alias"),
                _string(item.get("title"), "milestone.title"),
                _string(item.get("notes", ""), "milestone.notes", allow_empty=True),
                _strings(
                    item.get("concept_aliases", _MISSING),
                    "milestone.concept_aliases",
                ),
                _string(
                    item.get("existing_milestone_id", ""),
                    "existing_milestone_id",
                    allow_empty=True,
                ),
            )
        )

    concepts: list[ConceptProposal] = []
    for item in _objects(raw.get("concepts", _MISSING), "concepts"):
        _exact_keys(
            item,
            required=("alias", "display_label"),
            optional=("existing_concept_id",),
            label="concept",
        )
        concepts.append(
            ConceptProposal(
                _string(item.get("alias"), "concept.alias"),
                _string(item.get("display_label"), "concept.display_label"),
                _string(
                    item.get("existing_concept_id", ""),
                    "existing_concept_id",
                    allow_empty=True,
                ),
            )
        )

    relations: list[ConceptRelationProposal] = []
    for item in _objects(raw.get("concept_relations", _MISSING), "concept_relations"):
        _exact_keys(
            item,
            required=("source_alias", "target_alias", "relation", "reason", "provenance"),
            optional=(),
            label="concept relation",
        )
        relation = _string(item.get("relation"), "concept relation.relation")
        if relation not in {"equivalent", "broader", "narrower", "related", "distinct"}:
            raise CapabilityRefusedError("concept relation has an unsupported relation")
        relations.append(
            ConceptRelationProposal(
                _string(item.get("source_alias"), "concept relation.source_alias"),
                _string(item.get("target_alias"), "concept relation.target_alias"),
                relation,  # type: ignore[arg-type]
                _string(item.get("reason"), "concept relation.reason"),
                _string(item.get("provenance"), "concept relation.provenance"),
            )
        )

    dispositions: list[EvidenceDisposition] = []
    for item in _objects(raw.get("evidence_dispositions"), "evidence dispositions"):
        _exact_keys(
            item,
            required=("evidence_id", "disposition", "reason"),
            optional=(),
            label="evidence disposition",
        )
        disposition = _string(item.get("disposition"), "evidence disposition.disposition")
        if disposition not in {"selected", "rejected", "unresolved"}:
            raise CapabilityRefusedError("evidence disposition is unsupported")
        reason = _string(
            item.get("reason"),
            "evidence disposition.reason",
            allow_empty=True,
        )
        if disposition in {"rejected", "unresolved"} and not reason.strip():
            raise CapabilityRefusedError(f"{disposition} evidence requires a visible reason")
        dispositions.append(
            EvidenceDisposition(
                _string(item.get("evidence_id"), "evidence disposition.evidence_id"),
                disposition,
                reason,
            )
        )

    resources: list[Resource] = []
    for item in _objects(raw.get("resources", _MISSING), "resources"):
        _exact_keys(
            item,
            required=("label",),
            optional=("url", "note"),
            label="resource",
        )
        url = _string(item.get("url", ""), "resource.url", allow_empty=True)
        _validate_citation_url(url)
        resources.append(
            Resource(
                _string(item.get("label"), "resource.label"),
                url,
                _string(item.get("note", ""), "resource.note", allow_empty=True),
            )
        )

    unknowns: list[PlanUnknown] = []
    for item in _objects(raw.get("unknowns", _MISSING), "unknowns"):
        _exact_keys(
            item,
            required=("unknown_id", "question", "impact"),
            optional=("status",),
            label="unknown",
        )
        unknowns.append(
            PlanUnknown(
                _string(item.get("unknown_id"), "unknown.unknown_id"),
                _string(item.get("question"), "unknown.question"),
                _string(item.get("impact"), "unknown.impact"),
                _enum_string(
                    item.get("status", "open"),
                    "unknown.status",
                    frozenset({"open", "resolved"}),
                ),
            )
        )

    requested_status = _string(raw.get("requested_status", "draft"), "requested_status")
    if requested_status != "draft":
        raise CapabilityRefusedError("the model may only request draft plan status")
    return PlanProposalDraft(
        title=_string(raw.get("title"), "draft.title"),
        mission=mission,
        goals=tuple(goals),
        milestones=tuple(milestones),
        topics=_strings(raw.get("topics", _MISSING), "topics"),
        concepts=tuple(concepts),
        concept_relations=tuple(relations),
        evidence_dispositions=tuple(dispositions),
        resources=tuple(resources),
        unknowns=tuple(unknowns),
        next_action=_string(raw.get("next_action"), "next_action"),
        requested_status=requested_status,
        target_date=_string(raw.get("target_date", ""), "target_date", allow_empty=True),
        energy_floor=_bounded_integer(
            raw.get("energy_floor", _MISSING),
            "energy_floor",
            3,
            minimum=1,
            maximum=10,
        ),
        review_cadence_days=_bounded_integer(
            raw.get("review_cadence_days", _MISSING),
            "review_cadence_days",
            3,
            minimum=1,
        ),
        goal_limit_override_requested=_boolean(
            raw.get("goal_limit_override_requested", _MISSING),
            "goal_limit_override_requested",
        ),
        goal_limit_override_reason=_string(
            raw.get("goal_limit_override_reason", ""),
            "goal_limit_override_reason",
            allow_empty=True,
        ),
    )


def _validate_citation_url(url: str) -> None:
    if not url:
        return
    if len(url) > 2048 or any(ord(char) < 32 for char in url):
        raise CapabilityRefusedError(
            "resource citation URL has an invalid length or control character"
        )
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CapabilityRefusedError(
            "resource citation URL must be an inert absolute HTTP(S) citation"
        )
