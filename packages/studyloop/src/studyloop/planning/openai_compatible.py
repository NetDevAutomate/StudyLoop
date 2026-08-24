"""Fixed-destination OpenAI-compatible adapter for planning conversations."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

from .capabilities import PLANNING_CAPABILITY_SCHEMAS
from .model_config import (
    PlanningModelProfile,
    _literal_loopback_host,
    _peer_is_loopback,
    _resolve_api_key_reference,
)
from .model_port import (
    MODEL_WIRE_VERSION,
    ModelEvent,
    ModelRequest,
    ModelTextDelta,
    ModelToolCall,
    ModelTurnCompleted,
)


class ModelProtocolError(RuntimeError):
    """A provider stream could not be normalized without guessing."""


@dataclass(frozen=True, slots=True)
class GatewayRequest:
    url: str
    headers: Mapping[str, str]
    body: Mapping[str, object]
    connect_timeout_seconds: float
    turn_timeout_seconds: float
    max_sse_line_bytes: int = 131_072
    max_stream_bytes: int = 2_000_000


class GatewayTransport(Protocol):
    def stream(self, request: GatewayRequest) -> AsyncIterator[dict[str, object]]: ...


class HttpxGatewayTransport:
    """Production HTTP seam with proxy inheritance and redirects disabled."""

    async def stream(self, request: GatewayRequest) -> AsyncIterator[dict[str, object]]:
        timeout = httpx.Timeout(
            request.turn_timeout_seconds,
            connect=request.connect_timeout_seconds,
        )
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout) as client,
            client.stream(
                "POST",
                request.url,
                headers=dict(request.headers),
                json=dict(request.body),
            ) as response,
        ):
            if response.is_redirect:
                raise ModelProtocolError("planning gateway redirects are forbidden")
            if _literal_loopback_host(request.url) and not _peer_is_loopback(response):
                raise ModelProtocolError("planning gateway peer is not loopback")
            response.raise_for_status()
            async for payload in self._decode_sse_bytes(
                response.aiter_bytes(),
                max_line_bytes=request.max_sse_line_bytes,
                max_stream_bytes=request.max_stream_bytes,
            ):
                yield payload

    async def _decode_sse_bytes(
        self,
        chunks: AsyncIterator[bytes],
        *,
        max_line_bytes: int,
        max_stream_bytes: int,
    ) -> AsyncIterator[dict[str, object]]:
        """Bound raw SSE bytes before retaining a line or aggregate stream."""
        buffered = bytearray()
        aggregate = 0
        async for chunk in chunks:
            aggregate += len(chunk)
            if aggregate > max_stream_bytes:
                raise ModelProtocolError("planning gateway SSE aggregate bound exceeded")
            buffered.extend(chunk)
            while (newline := buffered.find(b"\n")) >= 0:
                line = bytes(buffered[:newline]).removesuffix(b"\r")
                del buffered[: newline + 1]
                if len(line) > max_line_bytes:
                    raise ModelProtocolError("planning gateway SSE line bound exceeded")
                done, payload = self._parse_sse_line(line)
                if done:
                    return
                if payload is not None:
                    yield payload
            if len(buffered) > max_line_bytes:
                raise ModelProtocolError("planning gateway SSE line bound exceeded")
        if buffered:
            done, payload = self._parse_sse_line(bytes(buffered))
            if not done and payload is not None:
                yield payload

    @staticmethod
    def _parse_sse_line(line: bytes) -> tuple[bool, dict[str, object] | None]:
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ModelProtocolError("planning gateway emitted malformed SSE text") from exc
        if not text or text.startswith(":"):
            return False, None
        if not text.startswith("data:"):
            raise ModelProtocolError("planning gateway emitted malformed SSE")
        data = text[5:].strip()
        if data == "[DONE]":
            return True, None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ModelProtocolError("planning gateway emitted malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ModelProtocolError("planning gateway chunk must be an object")
        return False, cast("dict[str, object]", payload)


@dataclass(slots=True)
class _PartialToolCall:
    tool_call_id: str = ""
    name_parts: list[str] = field(default_factory=list)
    argument_parts: list[str] = field(default_factory=list)
    name_characters: int = 0
    argument_characters: int = 0


class OpenAICompatiblePlanningModel:
    """Normalize one fixed-profile streaming response into the model port."""

    def __init__(
        self,
        profile: PlanningModelProfile,
        *,
        transport: GatewayTransport | None = None,
        max_tokens: int = 4096,
        max_stream_chunks: int = 2_048,
        max_stream_bytes: int = 2_000_000,
        max_sse_line_bytes: int = 131_072,
        max_partial_tool_name_characters: int = 128,
        max_partial_tool_argument_characters: int = 64_000,
    ) -> None:
        if isinstance(max_tokens, bool) or not 1 <= max_tokens <= 32_768:
            raise ValueError("planning max_tokens must be between 1 and 32768")
        self.profile = profile
        self.transport = transport or HttpxGatewayTransport()
        self.max_tokens = max_tokens
        stream_bounds = (
            max_stream_chunks,
            max_stream_bytes,
            max_sse_line_bytes,
            max_partial_tool_name_characters,
            max_partial_tool_argument_characters,
        )
        if any(isinstance(value, bool) or value <= 0 for value in stream_bounds):
            raise ValueError("planning gateway stream bounds must be positive integers")
        self.max_stream_chunks = max_stream_chunks
        self.max_stream_bytes = max_stream_bytes
        self.max_sse_line_bytes = max_sse_line_bytes
        self.max_partial_tool_name_characters = max_partial_tool_name_characters
        self.max_partial_tool_argument_characters = max_partial_tool_argument_characters

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        api_key = _resolve_api_key_reference(self.profile.api_key_ref)
        if self.profile.api_key_ref and api_key is None:
            raise ModelProtocolError("configured planning gateway credential is unavailable")
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        gateway_request = GatewayRequest(
            f"{self.profile.base_url}/chat/completions",
            headers,
            {
                "model": self.profile.model,
                "messages": [dict(message) for message in request.messages],
                "tools": [schema.to_wire() for schema in PLANNING_CAPABILITY_SCHEMAS],
                "tool_choice": "auto",
                "stream": True,
                "max_tokens": min(self.max_tokens, request.max_output_tokens),
            },
            self.profile.connect_timeout_seconds,
            self.profile.turn_timeout_seconds,
            self.max_sse_line_bytes,
            self.max_stream_bytes,
        )
        partial: dict[int, _PartialToolCall] = {}
        emitted_ids: set[str] = set()
        sequence = 0
        output_characters = 0
        terminal = False
        chunks_seen = 0
        aggregate_bytes = 0
        stream = self.transport.stream(gateway_request)
        try:
            async for chunk in stream:
                chunks_seen += 1
                if chunks_seen > self.max_stream_chunks:
                    raise ModelProtocolError("planning gateway chunk bound exceeded")
                try:
                    aggregate_bytes += len(
                        json.dumps(chunk, ensure_ascii=False, separators=(",", ":")).encode()
                    )
                except (TypeError, ValueError) as exc:
                    raise ModelProtocolError("planning gateway chunk is not serializable") from exc
                if aggregate_bytes > self.max_stream_bytes:
                    raise ModelProtocolError("planning gateway aggregate bound exceeded")
                choice = self._choice(chunk)
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    raise ModelProtocolError("planning gateway delta must be an object")
                if set(delta) & {"destination", "endpoint", "url", "headers", "tools", "schema"}:
                    raise ModelProtocolError(
                        "planning model cannot supply transport or capability controls"
                    )
                content = delta.get("content")
                if content is not None:
                    if not isinstance(content, str):
                        raise ModelProtocolError("planning gateway content must be text")
                    if content:
                        output_characters += len(content)
                        if output_characters > request.max_output_characters:
                            raise ModelProtocolError("planning gateway output bound exceeded")
                        sequence += 1
                        if sequence > request.max_events:
                            raise ModelProtocolError("planning gateway event bound exceeded")
                        yield ModelTextDelta(
                            MODEL_WIRE_VERSION,
                            request.turn_id,
                            request.attempt_id,
                            sequence,
                            content,
                        )
                raw_calls = delta.get("tool_calls")
                if raw_calls is not None:
                    if not isinstance(raw_calls, list):
                        raise ModelProtocolError("planning gateway tool_calls must be an array")
                    for raw_call in raw_calls:
                        self._accumulate_tool_call(partial, raw_call, request=request)
                finish_reason = choice.get("finish_reason")
                if finish_reason is not None:
                    if not isinstance(finish_reason, str):
                        raise ModelProtocolError("planning gateway finish reason must be text")
                    normalized_finish = (
                        finish_reason
                        if finish_reason in {"stop", "tool_calls", "length"}
                        else "error"
                    )
                    if normalized_finish == "tool_calls":
                        if not partial:
                            raise ModelProtocolError("tool completion contains no tool calls")
                        for index in sorted(partial):
                            call = partial[index]
                            if not call.tool_call_id or call.tool_call_id in emitted_ids:
                                raise ModelProtocolError(
                                    "planning gateway duplicated a tool-call ID"
                                )
                            emitted_ids.add(call.tool_call_id)
                            name = "".join(call.name_parts)
                            try:
                                arguments = json.loads("".join(call.argument_parts))
                            except json.JSONDecodeError as exc:
                                raise ModelProtocolError(
                                    "planning gateway emitted malformed tool arguments"
                                ) from exc
                            if not name or not isinstance(arguments, dict):
                                raise ModelProtocolError(
                                    "planning gateway emitted an invalid tool call"
                                )
                            sequence += 1
                            if sequence > request.max_events:
                                raise ModelProtocolError("planning gateway event bound exceeded")
                            yield ModelToolCall(
                                MODEL_WIRE_VERSION,
                                request.turn_id,
                                request.attempt_id,
                                sequence,
                                call.tool_call_id,
                                name,
                                cast("dict[str, object]", arguments),
                            )
                    elif partial:
                        raise ModelProtocolError(
                            "unfinished tool call ended without tool completion"
                        )
                    sequence += 1
                    if sequence > request.max_events:
                        raise ModelProtocolError("planning gateway event bound exceeded")
                    yield ModelTurnCompleted(
                        MODEL_WIRE_VERSION,
                        request.turn_id,
                        request.attempt_id,
                        sequence,
                        cast("Any", normalized_finish),
                    )
                    terminal = True
                    return
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                with suppress(Exception):
                    await close()
        if not terminal:
            raise ModelProtocolError("planning gateway stream ended without a finish reason")

    @staticmethod
    def _choice(chunk: Mapping[str, object]) -> Mapping[str, object]:
        choices = chunk.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ModelProtocolError("planning gateway chunk must contain exactly one choice")
        return cast("dict[str, object]", choices[0])

    def _accumulate_tool_call(
        self,
        partial: dict[int, _PartialToolCall],
        raw_call: object,
        *,
        request: ModelRequest,
    ) -> None:
        if not isinstance(raw_call, dict):
            raise ModelProtocolError("planning gateway tool call must be an object")
        if set(raw_call) & {"destination", "endpoint", "url", "headers", "schema"}:
            raise ModelProtocolError(
                "planning model cannot supply transport or capability controls"
            )
        index = raw_call.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ModelProtocolError("planning gateway tool-call index is invalid")
        if index not in partial and len(partial) >= request.max_tool_calls:
            raise ModelProtocolError("planning gateway partial tool-call bound exceeded")
        target = partial.setdefault(index, _PartialToolCall())
        call_id = raw_call.get("id")
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise ModelProtocolError("planning gateway tool-call ID is invalid")
            if target.tool_call_id and target.tool_call_id != call_id:
                raise ModelProtocolError("planning gateway changed a tool-call ID")
            if len(call_id) > min(
                self.max_partial_tool_name_characters,
                request.max_tool_name_characters,
            ):
                raise ModelProtocolError("planning gateway tool name bound exceeded")
            target.tool_call_id = call_id
        call_type = raw_call.get("type")
        if call_type is not None and call_type != "function":
            raise ModelProtocolError("planning gateway supports function tool calls only")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise ModelProtocolError("planning gateway tool function must be an object")
        if set(function) - {"name", "arguments"}:
            raise ModelProtocolError("planning gateway tool function contains unknown controls")
        name = function.get("name")
        arguments = function.get("arguments")
        if name is not None:
            if not isinstance(name, str):
                raise ModelProtocolError("planning gateway tool name fragment must be text")
            target.name_characters += len(name)
            if target.name_characters > min(
                self.max_partial_tool_name_characters,
                request.max_tool_name_characters,
            ):
                raise ModelProtocolError("planning gateway tool name bound exceeded")
            target.name_parts.append(name)
        if arguments is not None:
            if not isinstance(arguments, str):
                raise ModelProtocolError("planning gateway argument fragment must be text")
            target.argument_characters += len(arguments)
            if target.argument_characters > min(
                self.max_partial_tool_argument_characters,
                request.max_tool_argument_characters,
            ):
                raise ModelProtocolError("planning gateway tool argument bound exceeded")
            target.argument_parts.append(arguments)
