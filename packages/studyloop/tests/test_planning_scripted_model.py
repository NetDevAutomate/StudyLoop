"""Deterministic model adapter contract."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_scripted_model_uses_the_production_port_and_versioned_events() -> None:
    """A fake with a different event shape would leave the real runtime untested."""
    from studyloop.planning.model_port import (
        MODEL_WIRE_VERSION,
        ModelRequest,
        ModelTextDelta,
        ModelToolCall,
        ModelTurnCompleted,
    )
    from studyloop.planning.scripted_model import ScriptedPlanningModel, ScriptedResponse

    request = ModelRequest(
        schema_version=MODEL_WIRE_VERSION,
        conversation_id="conversation-1",
        turn_id="turn-1",
        attempt_id="attempt-1",
        messages=({"role": "user", "content": "A vague dump"},),
    )
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                turn_id="turn-1",
                events=(
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 1, "One question"),
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        2,
                        "tool-1",
                        "prepare_plan",
                        {},
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 3, "tool_calls"),
                ),
            ),
        )
    )

    events = [event async for event in model.stream(request)]

    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[1].name == "prepare_plan"
    assert model.requests == (request,)


@pytest.mark.asyncio
async def test_scripted_model_refuses_wrong_turn_or_non_monotonic_event_sequence() -> None:
    """Letting a script leak events across attempts would hide runtime correlation bugs."""
    from studyloop.planning.model_port import MODEL_WIRE_VERSION, ModelRequest, ModelTextDelta
    from studyloop.planning.scripted_model import (
        ScriptedModelError,
        ScriptedPlanningModel,
        ScriptedResponse,
    )

    request = ModelRequest(
        schema_version=MODEL_WIRE_VERSION,
        conversation_id="conversation-1",
        turn_id="turn-1",
        attempt_id="attempt-1",
        messages=(),
    )
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                turn_id="turn-1",
                events=(
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-other", "attempt-1", 2, "wrong"),
                    ModelTextDelta(MODEL_WIRE_VERSION, "turn-other", "attempt-1", 1, "order"),
                ),
            ),
        )
    )

    with pytest.raises(ScriptedModelError, match=r"turn|sequence"):
        _ = [event async for event in model.stream(request)]


def test_scripted_preflight_is_provider_free_and_exercises_exact_catalogue() -> None:
    """Setup must distinguish deterministic protocol readiness from live reachability."""
    from studyloop.planning.scripted_model import run_scripted_preflight

    result = run_scripted_preflight()

    assert result.ok
    assert result.capability_names == (
        "prepare_plan",
        "submit_plan_proposal",
        "get_plan_proposal",
    )
    assert result.lifecycle_operations == ("prepare", "handle", "inspect")
    assert result.live_provider_used is False
