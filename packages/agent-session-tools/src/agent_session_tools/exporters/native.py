"""Native archive adapters: origin comes from envelope structure, never prose.

These records supplement the legacy conversation view. No reasoning, system
prompts, image bytes or environment snapshots are collected. Invocation revision
and source machine remain unknown unless the native record establishes them;
session-start Git metadata cannot establish a later command's working tree.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from ..context.provenance import Origin
from ..context.store import NativeSource, _hash, _json


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.tzinfo is not None else None


def _body(value: Any) -> str:
    return value if isinstance(value, str) else _json(_without_binary(value))


def _without_binary(value: Any) -> Any:
    """Exclude explicitly typed media blocks, without interpreting arbitrary text."""
    if isinstance(value, dict):
        kind = value.get("type")
        if kind in ("image", "image_url", "input_image", "audio", "input_audio"):
            return {"type": "omitted_nontext", "native_type": kind}
        if len(value) == 1 and ("Image" in value or "Audio" in value):
            return {"type": "omitted_nontext", "native_type": next(iter(value))}
        return {k: _without_binary(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_binary(v) for v in value]
    return value


class NativeCollector:
    """A trusted parser accumulator; it does not write or classify project scope."""

    def __init__(
        self, session_id: str, harness: str, locator: str, parser_version: str
    ):
        self.session_id = session_id
        self.harness = harness
        self.locator = locator
        self.parser_version = parser_version
        self.sources: list[NativeSource] = []
        self._occurrences: Counter[str] = Counter()

    def key(self, record: Any, identity: Any = None) -> str:
        native_id = _text(identity)
        if native_id:
            return "native-id:" + native_id
        digest = _hash(_json(record))
        self._occurrences[digest] += 1
        return f"record-digest:{digest}:{self._occurrences[digest]}"

    def add(
        self,
        body: str,
        *,
        key: str,
        kind: str,
        pointer: str,
        origin: Origin,
        timestamp: Any = None,
        call_id: Any = None,
        target: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        self.sources.append(
            NativeSource(
                session_id=self.session_id,
                native_key=key,
                harness=self.harness,
                native_kind=kind,
                native_locator=self.locator + "#" + pointer,
                parser_version=self.parser_version,
                machine_id="unknown",
                body=body,
                origin=origin,
                recorded_at=_timestamp(timestamp),
                call_id=_text(call_id),
                target=target,
                exit_code=exit_code,
            )
        )

    def conversation(
        self,
        content: Any,
        *,
        role: Any,
        key: str,
        pointer: str,
        timestamp: Any,
    ) -> None:
        if role not in ("user", "assistant"):
            return
        if isinstance(content, str):
            if content.strip():
                self.add(
                    content,
                    key=key,
                    kind="message:" + role,
                    pointer=pointer,
                    origin=Origin.CONVERSATION,
                    timestamp=timestamp,
                )
            return
        if isinstance(content, list):
            for index, part in enumerate(content):
                if isinstance(part, str):
                    value = part
                    kind = "text"
                elif isinstance(part, dict) and part.get("type") in (
                    "text",
                    "input_text",
                    "output_text",
                ):
                    value = part.get("text")
                    kind = part["type"]
                else:
                    continue
                if isinstance(value, str) and value.strip():
                    self.add(
                        value,
                        key=f"{key}/text/{index}",
                        kind=f"message:{role}/{kind}",
                        pointer=f"{pointer}/{index}",
                        origin=Origin.CONVERSATION,
                        timestamp=timestamp,
                    )


def codex_record(collector: NativeCollector, record: dict, line: int) -> None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    timestamp = record.get("timestamp")
    pointer = f"line/{line}/payload"
    if record.get("type") == "response_item":
        kind = payload.get("type")
        if kind == "message":
            key = collector.key(payload, payload.get("id"))
            collector.conversation(
                payload.get("content"),
                role=payload.get("role"),
                key=key,
                pointer=pointer + "/content",
                timestamp=timestamp,
            )
        elif kind in ("function_call", "custom_tool_call"):
            call_id = payload.get("call_id")
            key = collector.key(payload, call_id)
            # An invocation is not a completed execution or an observed result.
            body = {
                name: payload.get(name)
                for name in ("name", "namespace", "arguments", "input")
            }
            collector.add(
                _body(body),
                key=key + "/invocation",
                kind=kind,
                pointer=pointer,
                origin=Origin.UNKNOWN,
                timestamp=timestamp,
                call_id=call_id,
            )
        elif kind in ("function_call_output", "custom_tool_call_output"):
            call_id = payload.get("call_id")
            collector.add(
                _body(payload.get("output")),
                key=collector.key(payload, call_id) + "/output",
                kind=kind,
                pointer=pointer + "/output",
                origin=Origin.TOOL_RESULT,
                timestamp=timestamp,
                call_id=call_id,
            )
        return
    if record.get("type") != "event_msg" or payload.get("type") != "item_completed":
        return
    item = payload.get("item")
    if not isinstance(item, dict):
        return
    kind = item.get("type")
    pointer += "/item"
    if kind == "CommandExecution":
        code = item.get("exit_code")
        terminal = item.get("status") in ("completed", "failed") and type(code) is int
        command = item.get("command")
        target = (
            _json(command)
            if (
                isinstance(command, list)
                and command
                and all(isinstance(v, str) for v in command)
            )
            else None
        )
        output = item.get("aggregated_output")
        if not isinstance(output, str):
            output = _json({"stdout": item.get("stdout"), "stderr": item.get("stderr")})
        collector.add(
            output,
            key=collector.key(item, item.get("id")) + "/execution",
            kind="event:CommandExecution",
            pointer=pointer,
            origin=Origin.PROCESS_EXIT if terminal else Origin.TOOL_RESULT,
            timestamp=timestamp,
            call_id=item.get("id"),
            target=target,
            exit_code=code if terminal else None,
        )
    elif kind in ("McpToolCall", "DynamicToolCall", "FunctionCallOutput"):
        value = (
            item.get("result")
            if kind == "McpToolCall"
            else (
                item.get("content_items")
                if kind == "DynamicToolCall"
                else item.get("output")
            )
        )
        collector.add(
            _body(value),
            key=collector.key(item, item.get("id")) + "/native-result",
            kind="event:" + kind,
            pointer=pointer,
            origin=Origin.TOOL_RESULT,
            timestamp=timestamp,
            call_id=item.get("id"),
        )


def claude_record(collector: NativeCollector, record: dict, line: int) -> None:
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") not in (
        "user",
        "assistant",
    ):
        return
    key = collector.key(record, record.get("uuid"))
    content = message.get("content")
    timestamp = record.get("timestamp")
    pointer = f"line/{line}/message/content"
    collector.conversation(
        content, role=message["role"], key=key, pointer=pointer, timestamp=timestamp
    )
    if not isinstance(content, list):
        return
    for index, part in enumerate(content):
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "tool_result":
            collector.add(
                _body(part.get("content")),
                key=f"{key}/result/{index}",
                kind="tool_result",
                pointer=f"{pointer}/{index}",
                origin=Origin.TOOL_RESULT,
                timestamp=timestamp,
                call_id=part.get("tool_use_id"),
            )
        elif kind == "tool_use":
            collector.add(
                _body({"name": part.get("name"), "input": part.get("input")}),
                key=f"{key}/invocation/{index}",
                kind="tool_use",
                pointer=f"{pointer}/{index}",
                origin=Origin.UNKNOWN,
                timestamp=timestamp,
                call_id=part.get("id"),
            )


def grok_record(collector: NativeCollector, record: dict, line: int) -> None:
    if record.get("synthetic_reason"):
        return
    kind = record.get("type")
    timestamp = record.get("timestamp")
    if kind in ("user", "assistant"):
        collector.conversation(
            record.get("content"),
            role=kind,
            key=collector.key(record, record.get("id")),
            pointer=f"line/{line}/content",
            timestamp=timestamp,
        )
    elif kind == "tool_result":
        collector.add(
            _body(record.get("content")),
            key=collector.key(record, record.get("tool_call_id")) + "/result",
            kind=kind,
            pointer=f"line/{line}/content",
            origin=Origin.TOOL_RESULT,
            timestamp=timestamp,
            call_id=record.get("tool_call_id"),
        )


def kiro_turn(
    collector: NativeCollector,
    turn: dict,
    *,
    pointer: str,
    timestamp: Any = None,
) -> None:
    content = turn.get("content")
    if isinstance(content, dict):
        prompt = content.get("Prompt")
        if isinstance(prompt, dict):
            collector.conversation(
                prompt.get("prompt"),
                role="user",
                key=collector.key(turn),
                pointer=pointer + "/content/Prompt/prompt",
                timestamp=timestamp,
            )
        for kind in ("ToolUseResults", "CancelledToolUses"):
            variant = content.get(kind)
            if not isinstance(variant, dict) or not isinstance(
                variant.get("tool_use_results"), list
            ):
                continue
            for index, result in enumerate(variant["tool_use_results"]):
                if isinstance(result, dict):
                    collector.add(
                        _body(result),
                        key=collector.key(result, result.get("tool_use_id"))
                        + "/result",
                        kind=kind,
                        pointer=f"{pointer}/content/{kind}/tool_use_results/{index}",
                        origin=Origin.TOOL_RESULT,
                        timestamp=timestamp,
                        call_id=result.get("tool_use_id"),
                    )
    for kind in ("Response", "ToolUse"):
        variant = turn.get(kind)
        if not isinstance(variant, dict):
            continue
        key = collector.key(variant, variant.get("message_id"))
        collector.conversation(
            variant.get("content"),
            role="assistant",
            key=key + "/text",
            pointer=f"{pointer}/{kind}/content",
            timestamp=timestamp,
        )
        if kind == "ToolUse" and isinstance(variant.get("tool_uses"), list):
            for index, call in enumerate(variant["tool_uses"]):
                if isinstance(call, dict):
                    # Exclude hidden model thinking; only the emitted invocation is retained.
                    body = {
                        k: call.get(k)
                        for k in ("name", "args", "orig_name", "orig_args")
                    }
                    collector.add(
                        _body(body),
                        key=collector.key(call, call.get("id")) + "/invocation",
                        kind=kind,
                        pointer=f"{pointer}/{kind}/tool_uses/{index}",
                        origin=Origin.UNKNOWN,
                        timestamp=timestamp,
                        call_id=call.get("id"),
                    )


def kiro_entry(collector: NativeCollector, entry: Any, index: int) -> None:
    pointer = f"history/{index}"
    if isinstance(entry, list):
        for turn_index, turn in enumerate(entry):
            if isinstance(turn, dict):
                kiro_turn(collector, turn, pointer=f"{pointer}/{turn_index}")
    elif isinstance(entry, dict):
        from .kiro import _epoch_ms_to_iso

        meta = entry.get("request_metadata")
        meta = meta if isinstance(meta, dict) else {}
        for role, field in (
            ("user", "request_start_timestamp_ms"),
            ("assistant", "stream_end_timestamp_ms"),
        ):
            turn = entry.get(role)
            if isinstance(turn, dict):
                timestamp = _timestamp(turn.get("timestamp")) or _epoch_ms_to_iso(
                    meta.get(field)
                )
                kiro_turn(
                    collector, turn, pointer=f"{pointer}/{role}", timestamp=timestamp
                )
