from __future__ import annotations

import ast
import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path

import pytest

from studyloop.planning.contracts import PlanningRequest
from studyloop.planning.conversation_contracts import (
    PRIVACY_NOTICE,
    AttachContext,
    ConversationConflictError,
    LearnerTurn,
    PlanningConversationBounds,
    PlanningConversationError,
)
from studyloop.planning.conversation_runtime import PlanningConversationRuntime
from studyloop.planning.conversation_store import ConversationStore
from studyloop.planning.lifecycle import PlanningLifecycle
from studyloop.planning.model_port import (
    MODEL_WIRE_VERSION,
    ModelTextDelta,
    ModelToolCall,
    ModelTurnCompleted,
)
from studyloop.planning.repository import PlanningPaths, PlanningRepository
from studyloop.planning.scripted_model import ScriptedPlanningModel, ScriptedResponse


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


@dataclass(frozen=True)
class _Brief:
    run_id: str = "run-bound"
    brief_context_digest: str = "sha256:v1:" + "b" * 64


class _CapturingLifecycle:
    def __init__(self) -> None:
        self.request_keys: list[str] = []

    def prepare(self, request, actor):
        self.request_keys.append(request.idempotency_key)
        return _Brief()

    def handle(self, command):  # pragma: no cover - not used by this contract test
        raise AssertionError(command)

    def inspect(self, ref):  # pragma: no cover - not used by this contract test
        raise AssertionError(ref)


class _FailingModel:
    async def stream(self, request):
        raise RuntimeError("provider unavailable")
        yield request  # pragma: no cover


class _LeakyFailingModel:
    async def stream(self, request):
        raise RuntimeError(
            "failed at http://127.0.0.1:4000/internal from /Users/private/config "
            "with provider-secret-value"
        )
        yield request  # pragma: no cover


class _RootPathDiagnosticModel:
    async def stream(self, request):
        raise ConversationConflictError("provider metadata from /secret and ~/secret")
        yield request  # pragma: no cover


class _HangingModel:
    async def stream(self, request):
        await asyncio.sleep(1)
        yield request  # pragma: no cover


class _BoundedInfiniteModel:
    def __init__(self) -> None:
        self.emitted = 0
        self.closed = False

    async def stream(self, request):
        try:
            while True:
                self.emitted += 1
                yield ModelTextDelta(
                    MODEL_WIRE_VERSION,
                    request.turn_id,
                    request.attempt_id,
                    self.emitted,
                    "x",
                )
                await asyncio.sleep(0)
        finally:
            self.closed = True


class _InfiniteToolModel:
    def __init__(self) -> None:
        self.emitted = 0
        self.closed = False

    async def stream(self, request):
        try:
            while True:
                self.emitted += 1
                yield ModelToolCall(
                    MODEL_WIRE_VERSION,
                    request.turn_id,
                    request.attempt_id,
                    self.emitted,
                    f"tool-{self.emitted}",
                    "prepare_plan",
                    {},
                )
                await asyncio.sleep(0)
        finally:
            self.closed = True


class _BoundaryFailure:
    def __init__(self, point: str, error_type: type[BaseException]) -> None:
        self.point = point
        self.error_type = error_type
        self.triggered = False

    def __call__(self, point: str) -> None:
        if point == self.point and not self.triggered:
            self.triggered = True
            raise self.error_type(f"failure at {point}")


class _TextModel:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            self.text,
        )
        yield ModelTurnCompleted(MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "stop")


class _PrepareThenFailModel:
    def __init__(self) -> None:
        self.round = 0

    async def stream(self, request):
        self.round += 1
        if self.round == 1:
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "prepare-1",
                "prepare_plan",
                {},
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "tool_calls"
            )
            return
        raise RuntimeError("provider disconnected after the durable tool result")


class _ResumeFromToolResultModel(_TextModel):
    async def stream(self, request):
        assert any(message.get("role") == "tool" for message in request.messages)
        async for event in super().stream(request):
            yield event


class _ProposalModel:
    """Script deterministic events while reading prior durable tool results."""

    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        round_number = len(self.requests)
        if round_number == 1:
            call = ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "prepare-1",
                "prepare_plan",
                {},
            )
            yield call
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                2,
                "tool_calls",
            )
            return
        prior = json.loads(request.messages[-1]["content"])
        payload = prior["payload"]
        if round_number == 2:
            arguments = {
                "run_id": payload["run_id"],
                "brief_context_digest": payload["brief_context_digest"],
                "draft": {
                    "title": "Protocol plan",
                    "mission": {
                        "why": "Turn vague intent into demonstrated understanding",
                        "success": ["Explain one protocol exchange"],
                    },
                    "goals": [
                        {
                            "alias": "trace",
                            "title": "Trace one protocol",
                            "reason": "The learner wants understanding rather than notes",
                            "alignment_rationale": "A trace makes the mission observable",
                        }
                    ],
                    "milestones": [
                        {
                            "alias": "trace-one",
                            "goal_alias": "trace",
                            "title": "Trace one request and response",
                        }
                    ],
                    "evidence_dispositions": [],
                    "next_action": "Trace one request and response",
                },
            }
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "submit-1",
                "submit_plan_proposal",
                arguments,
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                2,
                "tool_calls",
            )
            return
        if round_number == 3:
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "inspect-1",
                "get_plan_proposal",
                {"run_id": payload["run_id"], "proposal_id": payload["proposal_id"]},
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                2,
                "tool_calls",
            )
            return
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "I have prepared a provisional plan for your review.",
        )
        yield ModelTurnCompleted(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            2,
            "stop",
        )


class _StaleProposalModel:
    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        round_number = len(self.requests)
        if round_number == 1:
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "prepare-1",
                "prepare_plan",
                {},
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "tool_calls"
            )
            return
        if round_number == 2:
            prior = json.loads(request.messages[-1]["content"])["payload"]
            yield ModelToolCall(
                MODEL_WIRE_VERSION,
                request.turn_id,
                request.attempt_id,
                1,
                "submit-1",
                "submit_plan_proposal",
                {
                    "run_id": prior["run_id"],
                    "brief_context_digest": "sha256:v1:" + "f" * 64,
                    "draft": {
                        "title": "Stale plan",
                        "mission": {"why": "stale", "success": ["never persist"]},
                        "goals": [
                            {
                                "alias": "stale",
                                "title": "Stale",
                                "reason": "stale",
                                "alignment_rationale": "stale",
                            }
                        ],
                        "milestones": [
                            {
                                "alias": "stale",
                                "goal_alias": "stale",
                                "title": "Stale",
                            }
                        ],
                        "evidence_dispositions": [],
                        "next_action": "never",
                    },
                },
            )
            yield ModelTurnCompleted(
                MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "tool_calls"
            )
            return
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "The context changed, so I need to rebuild the proposal.",
        )
        yield ModelTurnCompleted(MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "stop")


def _lifecycle(tmp_path: Path) -> PlanningLifecycle:
    return PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(tmp_path / "planning"), index_refresher=None)
    )


@pytest.mark.asyncio
async def test_normal_clarification_persists_turn_message_and_disclosure(tmp_path: Path) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelTextDelta(
                        MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "What outcome matters?"
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "stop"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "planning" / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(store, model, _lifecycle(tmp_path))

    result = await runtime.accept_turn(
        "conversation-1",
        LearnerTurn(
            "turn-1",
            "I have lots of notes but no clear target",
            PlanningRequest("create", "I have lots of notes but no clear target", "request-1"),
        ),
    )

    assert result.status == "completed"
    assert result.privacy_notice == PRIVACY_NOTICE
    assert store.list_messages("conversation-1")[0].content == "What outcome matters?"
    request = model.requests[0]
    assert request.messages[-1]["content"] == "I have lots of notes but no clear target"
    assert PRIVACY_NOTICE not in request.messages[-1]["content"]


@pytest.mark.asyncio
async def test_unknown_tool_and_authority_injection_have_zero_capability_effects(
    tmp_path: Path,
) -> None:
    for name, arguments in (
        ("delete_plan", {}),
        ("prepare_plan", {"actor_kind": "learner"}),
    ):
        model = ScriptedPlanningModel(
            (
                ScriptedResponse(
                    "turn-1",
                    (
                        ModelToolCall(
                            MODEL_WIRE_VERSION,
                            "turn-1",
                            "attempt-1",
                            1,
                            "tool-1",
                            name,
                            arguments,
                        ),
                        ModelTurnCompleted(
                            MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"
                        ),
                    ),
                ),
            )
        )
        root = tmp_path / name
        store = ConversationStore(root / "conversations.sqlite3", ids=_Ids())
        runtime = PlanningConversationRuntime(store, model, _lifecycle(root))
        with pytest.raises(PlanningConversationError):
            await runtime.accept_turn(
                "conversation-1",
                LearnerTurn(
                    "turn-1",
                    "A dump",
                    PlanningRequest("create", "A dump", "request-1"),
                ),
            )
        assert store.list_capability_intents("turn-1") == []


@pytest.mark.asyncio
async def test_hard_tool_and_token_bounds_interrupt_attempt(tmp_path: Path) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "too long"),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "stop"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "planning" / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        model,
        _lifecycle(tmp_path),
        bounds=PlanningConversationBounds(
            max_tool_calls=1,
            max_output_tokens=7,
            max_output_characters=4,
        ),
    )
    with pytest.raises(PlanningConversationError, match="bound"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert store.list_attempts("turn-1")[0].status == "interrupted"
    assert model.requests[0].max_output_tokens == 7


@pytest.mark.asyncio
async def test_prepared_capability_key_is_the_key_observed_by_the_lifecycle(
    tmp_path: Path,
) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "tool-1",
                        "prepare_plan",
                        {},
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"),
                ),
            ),
            ScriptedResponse(
                "turn-1",
                (
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "Ready"),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "stop"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    lifecycle = _CapturingLifecycle()
    runtime = PlanningConversationRuntime(store, model, lifecycle)  # type: ignore[arg-type]

    await runtime.accept_turn(
        "conversation-1",
        LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-original")),
    )

    intent = store.list_capability_intents("turn-1")[0]
    assert lifecycle.request_keys == [intent.lifecycle_idempotency_key]


@pytest.mark.asyncio
async def test_provider_error_is_a_durable_explicit_interruption(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        _FailingModel(),
        _CapturingLifecycle(),  # type: ignore[arg-type]
    )

    with pytest.raises(PlanningConversationError, match="interrupted"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )

    assert store.list_attempts("turn-1")[0].status == "interrupted"
    assert store.replay_outbox("conversation-1", 0)[0].event_type == "attempt_interrupted"


@pytest.mark.asyncio
async def test_provider_diagnostic_metadata_is_not_persisted_in_interruption_reason(
    tmp_path: Path,
) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        _LeakyFailingModel(),  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
        configured_secret_values=("provider-secret-value",),
    )
    with pytest.raises(PlanningConversationError) as captured:
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    attempt = store.list_attempts("turn-1")[0]

    assert store.private_interruption_reason(attempt.attempt_id) == "RuntimeError"
    public_error = captured.value
    record = logging.LogRecord(
        "planning-test",
        logging.ERROR,
        __file__,
        1,
        "planning failed",
        (),
        (type(public_error), public_error, public_error.__traceback__),
    )
    rendered = "\n".join(
        (
            repr(public_error),
            "".join(traceback.format_exception(public_error)),
            logging.Formatter().format(record),
        )
    )
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    assert "127.0.0.1" not in rendered
    assert "/Users/private" not in rendered
    assert "provider-secret-value" not in rendered


@pytest.mark.asyncio
async def test_root_level_metadata_paths_are_removed_from_public_error_chain(
    tmp_path: Path,
) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        _RootPathDiagnosticModel(),  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
    )

    with pytest.raises(ConversationConflictError) as captured:
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )

    public_error = captured.value
    rendered = "\n".join((repr(public_error), "".join(traceback.format_exception(public_error))))
    assert public_error.__cause__ is None
    assert public_error.__context__ is None
    assert "/secret" not in rendered
    assert "~/secret" not in rendered
    assert store.private_interruption_reason("attempt-1") == "planning runtime detail redacted"


@pytest.mark.asyncio
async def test_wall_clock_bound_interrupts_a_hanging_provider(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        _HangingModel(),  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
        bounds=PlanningConversationBounds(turn_timeout_seconds=0.01),
    )

    with pytest.raises(PlanningConversationError, match="time bound"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert store.list_attempts("turn-1")[0].status == "interrupted"


@pytest.mark.asyncio
async def test_cancelling_a_live_provider_durably_interrupts_its_owned_attempt(
    tmp_path: Path,
) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        _HangingModel(),  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
    )
    task = asyncio.create_task(
        runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )
    for _ in range(100):
        await asyncio.sleep(0.001)
        if store.list_attempts("turn-1"):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert store.get_turn("conversation-1", "turn-1").status == "retryable"
    assert store.list_attempts("turn-1")[0].status == "interrupted"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize(
    ("boundary", "expected_turn_status", "expected_attempt_status", "expected_messages"),
    [
        ("before_finalized_message_commit", "retryable", "interrupted", 0),
        ("after_finalized_message_commit", "completed", "completed", 1),
        ("before_attempt_complete", "completed", "completed", 1),
        ("after_attempt_complete", "completed", "completed", 1),
    ],
)
async def test_exception_at_finalization_boundary_uses_durable_terminal_truth(
    tmp_path: Path,
    error_type: type[BaseException],
    boundary: str,
    expected_turn_status: str,
    expected_attempt_status: str,
    expected_messages: int,
) -> None:
    store = ConversationStore(tmp_path / boundary / error_type.__name__ / "conversations.sqlite3")
    runtime = PlanningConversationRuntime(
        store,
        _TextModel("Final answer"),
        _CapturingLifecycle(),  # type: ignore[arg-type]
        crash_injector=_BoundaryFailure(boundary, error_type),
    )

    with pytest.raises(error_type):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )

    assert store.get_turn("conversation-1", "turn-1").status == expected_turn_status
    assert [item.status for item in store.list_attempts("turn-1")] == [expected_attempt_status]
    assert len(store.list_messages("conversation-1")) == expected_messages


@pytest.mark.asyncio
async def test_infinite_model_stream_is_closed_as_soon_as_output_bound_is_crossed(
    tmp_path: Path,
) -> None:
    model = _BoundedInfiniteModel()
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        model,  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
        bounds=PlanningConversationBounds(
            max_output_characters=4,
            turn_timeout_seconds=1,
        ),
    )

    with pytest.raises(PlanningConversationError, match="output bound"):
        await asyncio.wait_for(
            runtime.accept_turn(
                "conversation-1",
                LearnerTurn(
                    "turn-1",
                    "A dump",
                    PlanningRequest("create", "A dump", "request-1"),
                ),
            ),
            timeout=0.2,
        )

    assert model.closed is True
    assert model.emitted == 5
    assert store.list_attempts("turn-1")[0].status == "interrupted"


@pytest.mark.asyncio
async def test_infinite_tool_stream_is_closed_at_tool_bound_before_buffering_more_calls(
    tmp_path: Path,
) -> None:
    model = _InfiniteToolModel()
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        model,  # type: ignore[arg-type]
        _CapturingLifecycle(),  # type: ignore[arg-type]
        bounds=PlanningConversationBounds(max_tool_calls=2),
    )

    with pytest.raises(PlanningConversationError, match="tool bound"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )

    assert model.closed is True
    assert model.emitted == 3
    assert store.list_capability_intents("turn-1") == []


def test_input_bound_counts_serialized_tool_call_arguments(tmp_path: Path) -> None:
    runtime = PlanningConversationRuntime(
        ConversationStore(tmp_path / "conversations.sqlite3"),
        ScriptedPlanningModel(()),
        _CapturingLifecycle(),  # type: ignore[arg-type]
        bounds=PlanningConversationBounds(max_input_characters=80),
    )
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "tool-1",
                "type": "function",
                "function": {
                    "name": "submit_plan_proposal",
                    "arguments": "x" * 200,
                },
            }
        ],
    }

    with pytest.raises(PlanningConversationError, match="input bound"):
        runtime._check_input_bound([message])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("x" * 1_000, {}, "name bound"),
        ("prepare_plan", {"extra": "x" * 100_000}, "argument bound"),
    ],
)
async def test_oversized_typed_tool_fields_stop_before_capability_intent(
    tmp_path: Path,
    name: str,
    arguments: dict[str, object],
    expected: str,
) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "tool-1",
                        name,
                        arguments,
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / expected / "conversations.sqlite3", ids=_Ids())

    with pytest.raises(PlanningConversationError, match=expected):
        await PlanningConversationRuntime(
            store,
            model,
            _CapturingLifecycle(),  # type: ignore[arg-type]
        ).accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )

    assert store.list_capability_intents("turn-1") == []


@pytest.mark.asyncio
async def test_duplicate_tool_call_ids_are_refused_before_any_intent(tmp_path: Path) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "same", "prepare_plan", {}
                    ),
                    ModelToolCall(
                        MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "same", "prepare_plan", {}
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 3, "tool_calls"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        model,
        _CapturingLifecycle(),  # type: ignore[arg-type]
    )

    with pytest.raises(PlanningConversationError, match="duplicated"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert store.list_capability_intents("turn-1") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bounds", "expected_message"),
    [
        (PlanningConversationBounds(max_model_rounds=1), "round bound"),
        (PlanningConversationBounds(max_tool_calls=1), "tool bound"),
    ],
)
async def test_model_round_and_tool_loop_bounds_are_hard(
    tmp_path: Path,
    bounds: PlanningConversationBounds,
    expected_message: str,
) -> None:
    responses = tuple(
        ScriptedResponse(
            "turn-1",
            (
                ModelToolCall(
                    MODEL_WIRE_VERSION,
                    "turn-1",
                    "attempt-1",
                    1,
                    f"tool-{index}",
                    "prepare_plan",
                    {},
                ),
                ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"),
            ),
        )
        for index in (1, 2)
    )
    store = ConversationStore(tmp_path / expected_message / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        ScriptedPlanningModel(responses),
        _CapturingLifecycle(),  # type: ignore[arg-type]
        bounds=bounds,
    )

    with pytest.raises(PlanningConversationError, match=expected_message):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert len(store.list_capability_intents("turn-1")) == 1


@pytest.mark.asyncio
async def test_second_prepare_is_out_of_sequence_and_has_zero_new_effects(tmp_path: Path) -> None:
    responses = tuple(
        ScriptedResponse(
            "turn-1",
            (
                ModelToolCall(
                    MODEL_WIRE_VERSION,
                    "turn-1",
                    "attempt-1",
                    1,
                    f"prepare-{index}",
                    "prepare_plan",
                    {},
                ),
                ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"),
            ),
        )
        for index in (1, 2)
    )
    lifecycle = _CapturingLifecycle()
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    runtime = PlanningConversationRuntime(
        store,
        ScriptedPlanningModel(responses),
        lifecycle,  # type: ignore[arg-type]
    )

    with pytest.raises(PlanningConversationError, match="already prepared"):
        await runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert len(store.list_capability_intents("turn-1")) == 1
    assert len(lifecycle.request_keys) == 1


@pytest.mark.asyncio
async def test_retry_reconstructs_projected_tool_results_without_resuming_tokens(
    tmp_path: Path,
) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    lifecycle = _CapturingLifecycle()
    first_runtime = PlanningConversationRuntime(
        store,
        _PrepareThenFailModel(),  # type: ignore[arg-type]
        lifecycle,  # type: ignore[arg-type]
    )
    with pytest.raises(PlanningConversationError):
        await first_runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    retry_version = store.get_turn("conversation-1", "turn-1").turn_version
    resume_model = _ResumeFromToolResultModel("A fresh response from the durable boundary")

    receipt = await PlanningConversationRuntime(
        store,
        resume_model,  # type: ignore[arg-type]
        lifecycle,  # type: ignore[arg-type]
    ).retry_turn(
        "conversation-1",
        "turn-1",
        expected_turn_version=retry_version,
    )

    assert receipt.status == "completed"
    assert [(item.attempt_seq, item.status) for item in store.list_attempts("turn-1")] == [
        (1, "interrupted"),
        (2, "completed"),
    ]


@pytest.mark.asyncio
async def test_later_turn_reconstructs_the_ordered_durable_transcript(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    lifecycle = _CapturingLifecycle()
    first_model = _TextModel("What would success look like?")
    await PlanningConversationRuntime(
        store,
        first_model,
        lifecycle,  # type: ignore[arg-type]
    ).accept_turn(
        "conversation-1",
        LearnerTurn(
            "turn-1",
            "I want to understand protocols",
            PlanningRequest("create", "I want to understand protocols", "request-1"),
        ),
    )
    second_model = _TextModel("Here is a provisional direction.")

    await PlanningConversationRuntime(
        store,
        second_model,
        lifecycle,  # type: ignore[arg-type]
    ).accept_turn(
        "conversation-1",
        LearnerTurn(
            "turn-2",
            "I want to explain one exchange",
            PlanningRequest("create", "I want to explain one exchange", "request-2"),
        ),
    )

    transcript = [
        (message["role"], message["content"])
        for message in second_model.requests[0].messages
        if message["role"] != "system"
    ]
    assert transcript == [
        ("user", "I want to understand protocols"),
        ("assistant", "What would success look like?"),
        ("user", "I want to explain one exchange"),
    ]


@pytest.mark.asyncio
async def test_tool_call_with_stop_finish_is_malformed_and_has_zero_effects(tmp_path: Path) -> None:
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "prepare-1",
                        "prepare_plan",
                        {},
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "stop"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    with pytest.raises(PlanningConversationError, match="finish reason"):
        await PlanningConversationRuntime(
            store,
            model,
            _CapturingLifecycle(),  # type: ignore[arg-type]
        ).accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    assert store.list_capability_intents("turn-1") == []


@pytest.mark.asyncio
async def test_channel_aware_capture_redacts_secrets_and_metadata_not_learner_paths(
    tmp_path: Path,
) -> None:
    configured_marker = "provider-sensitive-value"
    learner = (
        f"Use /Users/learner/course and https://course.test but never expose {configured_marker}"
    )
    context = f"Notes at /Users/learner/notes and https://notes.test mention {configured_marker}"
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "Question"),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "stop"),
                ),
            ),
        )
    )
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    store.attach_context(
        AttachContext(
            "conversation-1",
            "context-1",
            "http://127.0.0.1:4000/internal/source",
            context,
        )
    )
    runtime = PlanningConversationRuntime(
        store,
        model,
        _CapturingLifecycle(),  # type: ignore[arg-type]
        configured_secret_values=(configured_marker,),
    )

    await runtime.accept_turn(
        "conversation-1",
        LearnerTurn("turn-1", learner, PlanningRequest("create", learner, "request-1")),
    )

    captured = json.dumps(model.requests[0].messages, ensure_ascii=False)
    assert configured_marker not in captured
    assert "[REDACTED CONFIGURED SECRET]" in captured
    assert "/Users/learner/course" in captured and "https://course.test" in captured
    assert "/Users/learner/notes" in captured and "https://notes.test" in captured
    assert "127.0.0.1:4000" not in captured
    assert store.get_turn("conversation-1", "turn-1").learner_text == learner
    assert store.load_context("turn-1")[0].label == "selected text context"


@pytest.mark.asyncio
async def test_embedded_studyloop_metadata_locations_are_redacted_but_learner_text_is_verbatim(
    tmp_path: Path,
) -> None:
    learner = (
        "I typed /secret, ~/secret, /Users/learner/course.md and "
        "http://127.0.0.1:9999/my-example myself"
    )
    model = _TextModel("What would useful progress look like?")
    store = ConversationStore(tmp_path / "conversations.sqlite3", ids=_Ids())
    labels = (
        "Course from /secret (selected)",
        "Course from ~/secret (selected)",
        "Course from /Users/server/private/course.md (selected)",
        r"Imported from C:\\StudyLoop\\private\\course.txt today",
        "Loaded from file:///srv/studyloop/private/course.txt, selected",
        "Source http://127.0.0.1:4000/internal/course (local)",
        "Gateway 192.168.50.2:8080; selected",
        "Gateway [::1]:4000; selected",
    )
    for index, label in enumerate(labels, start=1):
        store.attach_context(
            AttachContext(
                "conversation-1",
                f"context-{index}",
                label,
                f"selected body {index}",
            )
        )

    await PlanningConversationRuntime(
        store,
        model,
        _CapturingLifecycle(),  # type: ignore[arg-type]
    ).accept_turn(
        "conversation-1",
        LearnerTurn("turn-1", learner, PlanningRequest("create", learner, "request-1")),
    )

    captured = json.dumps(model.requests[0].messages, ensure_ascii=False)
    assert all(item.label == "selected text context" for item in store.load_context("turn-1"))
    assert "/Users/server" not in captured
    assert "C:\\\\StudyLoop" not in captured
    assert "file:///srv/studyloop" not in captured
    assert "127.0.0.1:4000" not in captured
    assert "192.168.50.2:8080" not in captured
    assert "/secret" in captured
    assert "~/secret" in captured
    assert "/Users/learner/course.md" in captured
    assert "127.0.0.1:9999/my-example" in captured
    assert store.get_turn("conversation-1", "turn-1").learner_text == learner


@pytest.mark.asyncio
async def test_real_lifecycle_proposal_round_trip_preserves_existing_recovery_truth(
    tmp_path: Path,
) -> None:
    root = tmp_path / "planning"
    store = ConversationStore(root / "conversations.sqlite3", ids=_Ids())
    model = _ProposalModel()
    lifecycle = PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
    )
    runtime = PlanningConversationRuntime(store, model, lifecycle)  # type: ignore[arg-type]
    learner = "I have collected protocol notes but do not know what to practise"

    receipt = await runtime.accept_turn(
        "conversation-1",
        LearnerTurn("turn-1", learner, PlanningRequest("create", learner, "request-1")),
    )

    assert receipt.status == "completed"
    assert len(model.requests) == 4
    assert [event.event_type for event in store.replay_outbox("conversation-1", 0)] == [
        "capability_result",
        "capability_result",
        "capability_result",
        "assistant_message",
    ]
    journal_events = [
        json.loads(line) for line in (root / "planning-journal.jsonl").read_text().splitlines()
    ]
    lifecycle_types = [
        event["payload"]["lifecycle"]["type"]
        for event in journal_events
        if event["event"] == "committed" and "lifecycle" in event["payload"]
    ]
    assert lifecycle_types == ["run_captured", "proposal_issued"]
    run_dirs = list((root / "private-runs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "brain-dump.txt").read_text() == learner
    proposal_files = list(run_dirs[0].glob("proposal-*.json"))
    assert len(proposal_files) == 1 and "Protocol plan" in proposal_files[0].read_text()
    assert list((root / "plans").glob("*.md")) == []
    assert not (root / "studyloop.db").exists()


@pytest.mark.asyncio
async def test_proposal_with_a_different_frozen_brief_digest_is_durably_refused(
    tmp_path: Path,
) -> None:
    root = tmp_path / "planning"
    store = ConversationStore(root / "conversations.sqlite3", ids=_Ids())
    lifecycle = PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
    )
    learner = "Use this exact context snapshot"
    runtime = PlanningConversationRuntime(
        store,
        _StaleProposalModel(),
        lifecycle,  # type: ignore[arg-type]
    )

    receipt = await runtime.accept_turn(
        "conversation-1",
        LearnerTurn("turn-1", learner, PlanningRequest("create", learner, "request-1")),
    )

    assert receipt.status == "completed"
    intents = store.list_capability_intents("turn-1")
    assert [item.status for item in intents] == ["projected", "refused"]
    assert [event.event_type for event in store.replay_outbox("conversation-1", 0)] == [
        "capability_result",
        "capability_result",
        "assistant_message",
    ]
    run_dirs = list((root / "private-runs").iterdir())
    assert len(run_dirs) == 1
    assert list(run_dirs[0].glob("proposal-*.json")) == []


def test_planning_conversation_modules_do_not_import_general_agent_stacks() -> None:
    planning = Path(__file__).parents[1] / "src" / "studyloop" / "planning"
    forbidden = {"subprocess", "fastmcp", "studyloop.mcp", "studyloop.agent_workspace"}
    imported: set[str] = set()
    for name in ("conversation_runtime.py", "openai_compatible.py"):
        tree = ast.parse((planning / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.lower())
    assert not any(any(item.startswith(blocked) for blocked in forbidden) for item in imported)
