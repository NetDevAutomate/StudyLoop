from __future__ import annotations

from dataclasses import replace

import pytest

from studyloop.planning.capabilities import PLANNING_CAPABILITY_SCHEMAS
from studyloop.planning.model_config import PlanningModelProfile
from studyloop.planning.model_port import (
    MODEL_WIRE_VERSION,
    ModelRequest,
    ModelToolCall,
    ModelTurnCompleted,
)
from studyloop.planning.openai_compatible import (
    GatewayRequest,
    HttpxGatewayTransport,
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


class _InfiniteTransport:
    def __init__(self, chunk: dict[str, object]) -> None:
        self.chunk = chunk
        self.emitted = 0
        self.closed = False

    async def stream(self, request: GatewayRequest):
        try:
            while True:
                self.emitted += 1
                yield self.chunk
        finally:
            self.closed = True


async def _bytes(*chunks: bytes):
    for chunk in chunks:
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
    messages = sent.body["messages"]
    assert isinstance(messages, list)
    final_message = messages[-1]
    assert isinstance(final_message, dict)
    assert final_message["content"] == _request().messages[-1]["content"]
    completed = events[-1]
    assert isinstance(completed, ModelTurnCompleted)
    assert completed.finish_reason == "stop"


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
    chunks: tuple[dict[str, object], ...] = (
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


@pytest.mark.asyncio
async def test_adapter_stops_an_infinite_chunk_stream_at_the_aggregate_bound() -> None:
    transport = _InfiniteTransport(
        {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=transport,
        max_stream_chunks=4,
        max_stream_bytes=1_024,
    )

    with pytest.raises(ModelProtocolError, match="chunk bound"):
        _ = [event async for event in client.stream(_request())]

    assert transport.closed is True
    assert transport.emitted == 5


@pytest.mark.asyncio
async def test_adapter_enforces_request_output_bound_before_emitting_an_extra_delta() -> None:
    transport = _InfiniteTransport(
        {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=transport,
    )

    with pytest.raises(ModelProtocolError, match="output bound"):
        _ = [event async for event in client.stream(replace(_request(), max_output_characters=4))]

    assert transport.closed is True
    assert transport.emitted == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "fragment", "expected"),
    [
        ("name", "prepare_", "name bound"),
        ("arguments", "x" * 12, "argument bound"),
    ],
)
async def test_fragmented_tool_fields_are_bounded_during_accumulation(
    field: str,
    fragment: str,
    expected: str,
) -> None:
    function = {field: fragment}
    transport = _InfiniteTransport(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "tool-1",
                                "type": "function",
                                "function": function,
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    client = OpenAICompatiblePlanningModel(
        PlanningModelProfile.from_explicit(base_url="http://127.0.0.1:4000/v1", model="premier"),
        transport=transport,
        max_partial_tool_name_characters=12,
        max_partial_tool_argument_characters=20,
    )

    with pytest.raises(ModelProtocolError, match=expected):
        _ = [event async for event in client.stream(_request())]

    assert transport.closed is True
    assert transport.emitted <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunks", "line_limit", "aggregate_limit", "expected"),
    [
        ((b"data: " + b"x" * 40,), 24, 100, "line bound"),
        ((b"data: {}\n", b"data: {}\n", b"data: {}\n"), 24, 20, "aggregate bound"),
    ],
)
async def test_http_transport_bounds_raw_sse_before_unbounded_line_buffering(
    chunks: tuple[bytes, ...],
    line_limit: int,
    aggregate_limit: int,
    expected: str,
) -> None:
    transport = HttpxGatewayTransport()

    with pytest.raises(ModelProtocolError, match=expected):
        _ = [
            payload
            async for payload in transport._decode_sse_bytes(
                _bytes(*chunks),
                max_line_bytes=line_limit,
                max_stream_bytes=aggregate_limit,
            )
        ]
