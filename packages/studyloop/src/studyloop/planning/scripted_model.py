"""Deterministic provider-free adapter for planning protocol tests and readiness."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .capabilities import (
    PLANNING_CAPABILITY_SCHEMAS,
    PlanningCapabilityCall,
    PlanningCapabilityDispatcher,
)
from .contracts import ActorContext, PlanningCommand, PlanningRequest, ProposalRef
from .model_port import (
    MODEL_WIRE_VERSION,
    ModelEvent,
    ModelRequest,
    ModelToolCall,
    ModelTurnCompleted,
)


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
    live_provider_used: bool = False


@dataclass(frozen=True, slots=True)
class _PreflightBrief:
    run_id: str = "preflight-run"


@dataclass(frozen=True, slots=True)
class _PreflightReview:
    run_id: str = "preflight-run"
    proposal_id: str = "preflight-proposal"


class _PreflightLifecycle:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def prepare(self, request: PlanningRequest, actor: ActorContext) -> object:
        del request, actor
        self.operations.append("prepare")
        return _PreflightBrief()

    def handle(self, command: PlanningCommand) -> object:
        del command
        self.operations.append("handle")
        return _PreflightReview()

    def inspect(self, ref: ProposalRef) -> object:
        del ref
        self.operations.append("inspect")
        return _PreflightReview()


async def _scripted_preflight() -> ScriptedPreflightResult:
    names = tuple(item.name.value for item in PLANNING_CAPABILITY_SCHEMAS)
    arguments: tuple[dict[str, object], ...] = (
        {},
        {
            "run_id": "preflight-run",
            "brief_context_digest": "sha256:v1:" + "b" * 64,
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
                "next_action": "Run the scripted preflight",
            },
        },
        {"run_id": "preflight-run", "proposal_id": "preflight-proposal"},
    )
    tool_events = (
        ModelToolCall(
            MODEL_WIRE_VERSION,
            "preflight-turn",
            "preflight-attempt",
            sequence,
            f"preflight-{sequence}",
            name,
            arguments[sequence - 1],
        )
        for sequence, name in enumerate(names, start=1)
    )
    events: tuple[ModelEvent, ...] = (
        *tool_events,
        ModelTurnCompleted(
            MODEL_WIRE_VERSION,
            "preflight-turn",
            "preflight-attempt",
            len(names) + 1,
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
    observed_names = tuple(event.name for event in observed if isinstance(event, ModelToolCall))
    lifecycle = _PreflightLifecycle()
    dispatcher = PlanningCapabilityDispatcher(
        lifecycle,
        PlanningRequest("create", "Provider-free preflight", "preflight-request"),
    )
    results = [
        dispatcher.execute(PlanningCapabilityCall(event.tool_call_id, event.name, event.arguments))
        for event in observed
        if isinstance(event, ModelToolCall)
    ]
    operations = tuple(lifecycle.operations)
    return ScriptedPreflightResult(
        observed_names == names
        and all(item.status == "ok" for item in results)
        and operations == ("prepare", "handle", "inspect"),
        observed_names,
        operations,
    )


def run_scripted_preflight() -> ScriptedPreflightResult:
    """Run the deterministic port check from synchronous setup/doctor code."""
    return asyncio.run(_scripted_preflight())
