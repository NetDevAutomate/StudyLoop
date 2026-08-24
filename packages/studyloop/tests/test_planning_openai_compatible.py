from __future__ import annotations

import pytest

from studyloop.planning.capabilities import PLANNING_CAPABILITY_SCHEMAS
from studyloop.planning.model_config import PlanningModelProfile
from studyloop.planning.model_port import MODEL_WIRE_VERSION, ModelRequest, ModelToolCall
from studyloop.planning.openai_compatible import (
    GatewayRequest,
    ModelProtocolError,
    OpenAICompatiblePlanningModel,
)


class _Transport:
    def __init__(self, chunks: tuple[dict[str, object], ...]) -> None:
        self.chunks = chunks
        self.requests: list[GatewayRequest] = []

    async def stream(self, request: GatewayRequest):
        self.requests.append(request)
        for chunk in self.chunks:
            yield chunk


def _request(content: str = "Learner text /tmp/example https://example.test") -> ModelRequest:
    return ModelRequest(
        MODEL_WIRE_VERSION,
        "conversation-1",
        "turn-1",
        "attempt-1",
        ({"role": "user", "content": content},),
    )


@pytest.mark.asyncio
async def test_adapter_uses_fixed_gateway_and_exact_three_schemas() -> None:
    transport = _Transport(
        (
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=transport,
    )

    events = [event async for event in client.stream(_request())]

    sent = transport.requests[0]
    assert sent.url == "http://127.0.0.1:4000/v1/chat/completions"
    assert sent.body["model"] == "premier"
    assert sent.body["max_tokens"] == 4096
    assert sent.body["tools"] == [schema.to_wire() for schema in PLANNING_CAPABILITY_SCHEMAS]
    assert sent.body["messages"][-1]["content"] == _request().messages[-1]["content"]
    assert events[-1].finish_reason == "stop"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_fragmented_tool_call_is_normalized_to_one_typed_call() -> None:
    transport = _Transport(
        (
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "tool-1",
                                    "type": "function",
                                    "function": {"name": "prepare_", "arguments": "{"},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"name": "plan", "arguments": "}"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=transport,
    )

    events = [event async for event in client.stream(_request())]

    call = next(event for event in events if isinstance(event, ModelToolCall))
    assert (call.tool_call_id, call.name, call.arguments) == ("tool-1", "prepare_plan", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks",
    [
        ({"choices": []},),
        ({"choices": [{"delta": {"tool_calls": "forged"}, "finish_reason": None}]},),
        (
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "tool-1",
                                    "function": {"name": "prepare_plan", "arguments": "not-json"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ),
    ],
)
async def test_malformed_stream_is_refused(chunks: tuple[dict[str, object], ...]) -> None:
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=_Transport(chunks),
    )
    with pytest.raises(ModelProtocolError):
        _ = [event async for event in client.stream(_request())]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forged_delta",
    [
        {"content": "hello", "destination": "https://attacker.test/v1"},
        {"content": "hello", "headers": {"Authorization": "forged"}},
        {"content": "hello", "tools": []},
        {"content": "hello", "schema": {"type": "object"}},
    ],
)
async def test_model_supplied_transport_or_schema_controls_are_refused(
    forged_delta: dict[str, object],
) -> None:
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=_Transport(({"choices": [{"delta": forged_delta, "finish_reason": "stop"}]},)),
    )

    with pytest.raises(ModelProtocolError, match="control"):
        _ = [event async for event in client.stream(_request())]


@pytest.mark.asyncio
async def test_duplicate_tool_call_ids_across_indices_are_refused() -> None:
    chunks = (
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "same",
                                "type": "function",
                                "function": {"name": "prepare_plan", "arguments": "{}"},
                            },
                            {
                                "index": 1,
                                "id": "same",
                                "type": "function",
                                "function": {"name": "prepare_plan", "arguments": "{}"},
                            },
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=_Transport(chunks),
    )

    with pytest.raises(ModelProtocolError, match="duplicated"):
        _ = [event async for event in client.stream(_request())]
