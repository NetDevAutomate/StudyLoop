"""Deterministic provider-free adapter for planning protocol tests and readiness."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .capabilities import (
    PLANNING_CAPABILITY_SCHEMAS,
    PlanningCapabilityCall,
    PlanningCapabilityDispatcher,
    PlanningCapabilityScope,
)
from .contracts import (
    ActorContext,
    PlanningCommand,
    PlanningRequest,
    ProposalRef,
)
from .evidence import EvidenceCatalogue
from .lifecycle import PlanningLifecycle
from .model_port import (
    MODEL_WIRE_VERSION,
    ModelEvent,
    ModelRequest,
    ModelToolCall,
    ModelTurnCompleted,
)
from .models import EvidenceRef
from .repository import PlanningPaths, PlanningRepository


class ScriptedModelError(RuntimeError):
    """A deterministic script does not match the requested attempt."""


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    turn_id: str
    events: tuple[ModelEvent, ...]


class ScriptedPlanningModel:
    """One response per request, validated through the production wire contract."""

    def __init__(self, responses: tuple[ScriptedResponse, ...]) -> None:
        self._responses = responses
        self._index = 0
        self._requests: list[ModelRequest] = []

    @property
    def requests(self) -> tuple[ModelRequest, ...]:
        return tuple(self._requests)

    async def stream(self, request: ModelRequest):
        if self._index >= len(self._responses):
            raise ScriptedModelError("script has no response for this turn")
        response = self._responses[self._index]
        self._index += 1
        self._requests.append(request)
        if response.turn_id != request.turn_id:
            raise ScriptedModelError("scripted response turn does not match request turn")
        prior_sequence = 0
        for event in response.events:
            if event.schema_version != MODEL_WIRE_VERSION:
                raise ScriptedModelError("scripted event has unsupported wire version")
            if event.turn_id != request.turn_id or event.attempt_id != request.attempt_id:
                raise ScriptedModelError("scripted event turn or attempt does not match request")
            if event.sequence <= prior_sequence:
                raise ScriptedModelError("scripted event sequence is not strictly increasing")
            prior_sequence = event.sequence
            yield event


@dataclass(frozen=True, slots=True)
class ScriptedPreflightResult:
    ok: bool
    capability_names: tuple[str, ...]
    lifecycle_operations: tuple[str, ...]
    validated_evidence_ids: tuple[str, ...]
    live_provider_used: bool = False


class _PreflightClock:
    def now(self) -> str:
        return "2026-08-24T12:00:00+00:00"


class _PreflightIds:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        value = self._counts.get(prefix, 0) + 1
        self._counts[prefix] = value
        return f"{prefix}-preflight-{value}"


class _PreflightLifecycle:
    def __init__(self, target: PlanningLifecycle) -> None:
        self.target = target
        self.operations: list[str] = []
        self.last_result: object | None = None

    def prepare(self, request: PlanningRequest, actor: ActorContext) -> object:
        self.operations.append("prepare")
        self.last_result = self.target.prepare(request, actor)
        return self.last_result

    def handle(self, command: PlanningCommand) -> object:
        self.operations.append("handle")
        self.last_result = self.target.handle(command)
        return self.last_result

    def inspect(self, ref: ProposalRef) -> object:
        self.operations.append("inspect")
        self.last_result = self.target.inspect(ref)
        return self.last_result


async def _scripted_preflight() -> ScriptedPreflightResult:
    names = tuple(item.name.value for item in PLANNING_CAPABILITY_SCHEMAS)
    evidence_id = "preflight-evidence"
    evidence = EvidenceRef(
        evidence_id=evidence_id,
        source_kind="supplied_material",
        source_native_id="preflight-material",
        source_revision="1",
        observed_at="2026-08-24T10:00:00+00:00",
        ingested_at="2026-08-24T11:00:00+00:00",
        tier=4,
        claim_kind="context",
        subject_ref="concept:preflight",
        provenance_digest="sha256:v1:" + "e" * 64,
    )
    with TemporaryDirectory(prefix="studyloop-planning-preflight-") as temp_dir:
        target = PlanningLifecycle(
            PlanningRepository(PlanningPaths.in_root(Path(temp_dir)), index_refresher=None),
            clock=_PreflightClock(),
            ids=_PreflightIds(),
            evidence=EvidenceCatalogue((evidence,)),
        )
        lifecycle = _PreflightLifecycle(target)
        dispatcher = PlanningCapabilityDispatcher(
            lifecycle,
            PlanningRequest(
                "create",
                "Provider-free preflight",
                "preflight-request",
                evidence_ids=(evidence_id,),
            ),
            scope=PlanningCapabilityScope(
                "preflight-conversation", "preflight-turn", "preflight-attempt"
            ),
        )
        observed_names: list[str] = []

        async def dispatch_scripted_call(
            index: int,
            name: str,
            arguments: dict[str, object],
        ):
            events: tuple[ModelEvent, ...] = (
                ModelToolCall(
                    MODEL_WIRE_VERSION,
                    "preflight-turn",
                    "preflight-attempt",
                    1,
                    f"preflight-{index}",
                    name,
                    arguments,
                ),
                ModelTurnCompleted(
                    MODEL_WIRE_VERSION,
                    "preflight-turn",
                    "preflight-attempt",
                    2,
                    "tool_calls",
                ),
            )
            model = ScriptedPlanningModel((ScriptedResponse("preflight-turn", events),))
            request = ModelRequest(
                MODEL_WIRE_VERSION,
                "preflight-conversation",
                "preflight-turn",
                "preflight-attempt",
                (),
            )
            observed = [event async for event in model.stream(request)]
            tool_call = next(event for event in observed if isinstance(event, ModelToolCall))
            observed_names.append(tool_call.name)
            return dispatcher.execute(
                PlanningCapabilityCall(
                    tool_call.tool_call_id,
                    tool_call.name,
                    tool_call.arguments,
                )
            )

        prepared = await dispatch_scripted_call(1, names[0], {})
        run_id = prepared.payload["run_id"]
        brief_digest = prepared.payload["brief_context_digest"]
        if not isinstance(run_id, str) or not isinstance(brief_digest, str):
            raise ScriptedModelError("real preflight returned an invalid planning brief")
        submitted = await dispatch_scripted_call(
            2,
            names[1],
            {
                "run_id": run_id,
                "brief_context_digest": brief_digest,
                "draft": {
                    "title": "Preflight plan",
                    "mission": {
                        "why": "Verify the confined protocol",
                        "success": ["All three capabilities cross the same seam"],
                    },
                    "goals": [
                        {
                            "alias": "verify",
                            "title": "Verify the protocol",
                            "reason": "Setup needs deterministic evidence",
                            "alignment_rationale": "This is protocol-only readiness",
                        }
                    ],
                    "milestones": [
                        {
                            "alias": "exercise",
                            "goal_alias": "verify",
                            "title": "Exercise all allowed calls",
                        }
                    ],
                    "evidence_dispositions": [
                        {
                            "evidence_id": evidence_id,
                            "disposition": "unresolved",
                            "reason": "Preflight context does not demonstrate learning",
                        }
                    ],
                    "next_action": "Run the scripted preflight",
                },
            },
        )
        proposal_id = submitted.payload["proposal_id"]
        if not isinstance(proposal_id, str):
            raise ScriptedModelError("real preflight returned an invalid proposal")
        await dispatch_scripted_call(
            3,
            names[2],
            {"run_id": run_id, "proposal_id": proposal_id},
        )
        review = lifecycle.last_result
        plan = getattr(review, "plan_preview", None)
        offered_ids = tuple(item.evidence_id for item in getattr(plan, "evidence", ()))
        disposition_ids = tuple(
            item.evidence_id for item in getattr(plan, "evidence_dispositions", ())
        )
        operations = tuple(lifecycle.operations)
        validated_evidence_ids = disposition_ids if disposition_ids == offered_ids else ()
        observed = tuple(observed_names)
        return ScriptedPreflightResult(
            observed == names
            and operations == ("prepare", "handle", "inspect")
            and validated_evidence_ids == (evidence_id,),
            observed,
            operations,
            validated_evidence_ids,
        )


def run_scripted_preflight() -> ScriptedPreflightResult:
    """Run the deterministic port check from synchronous setup/doctor code."""
    return asyncio.run(_scripted_preflight())
