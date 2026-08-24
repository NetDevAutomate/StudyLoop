"""Bounded application service for durable, confined planning conversations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .capabilities import (
    CapabilityRefusedError,
    PlanningCapabilityCall,
    PlanningCapabilityDispatcher,
    PlanningCapabilityScope,
    normalize_planning_capability_call,
)
from .contracts import LifecycleError
from .conversation_contracts import (
    AttemptRecord,
    BeginModelAttempt,
    CaptureLearnerTurn,
    CompleteModelAttempt,
    ConversationConflictError,
    FinalizeAssistantMessage,
    LearnerTurn,
    MarkAttemptInterrupted,
    PlanningConversationBounds,
    PlanningConversationError,
    PrepareCapabilityCall,
    ProjectCapabilityResult,
    RecoveryResult,
    StoredCapabilityResult,
    TurnReceipt,
)
from .model_port import (
    MODEL_WIRE_VERSION,
    ModelEvent,
    ModelRequest,
    ModelTextDelta,
    ModelToolCall,
    ModelTurnCompleted,
    PlanningModelPort,
    load_architect_prompt,
)
from .repository import PlanningRepositoryError

if TYPE_CHECKING:
    from .conversation_store import ConversationStore
    from .lifecycle import PlanningLifecycle

CrashInjector = Callable[[str], None]
_VISIBLE_SECRET_MARKER = "[REDACTED CONFIGURED SECRET]"


class ModelAttemptError(PlanningConversationError):
    """A provider attempt ended without a trustworthy finalized result."""


class PlanningConversationRuntime:
    """Coordinate SQLite intent/outbox truth with journalled lifecycle truth."""

    def __init__(
        self,
        store: ConversationStore,
        model: PlanningModelPort,
        lifecycle: PlanningLifecycle,
        *,
        bounds: PlanningConversationBounds | None = None,
        configured_secret_values: Iterable[str] = (),
        crash_injector: CrashInjector | None = None,
    ) -> None:
        self.store = store
        self.model = model
        self.lifecycle = lifecycle
        self.bounds = bounds or PlanningConversationBounds()
        self._secret_values = tuple(
            sorted(
                {value for value in configured_secret_values if value},
                key=len,
                reverse=True,
            )
        )
        self._crash_injector = crash_injector

    async def accept_turn(self, conversation_id: str, turn: LearnerTurn) -> TurnReceipt:
        """Durably capture a turn, then run exactly one bounded model attempt."""
        receipt = self.store.capture_turn_and_freeze_context(
            CaptureLearnerTurn(conversation_id, turn)
        )
        if receipt.status == "completed":
            return receipt
        if receipt.status != "ready":
            raise ConversationConflictError("learner turn is already scheduled or retryable")
        attempt = self.store.begin_attempt(
            BeginModelAttempt(conversation_id, turn.turn_id, receipt.turn_version, None)
        )
        try:
            async with asyncio.timeout(self.bounds.turn_timeout_seconds):
                completed = await self._execute_attempt(attempt)
        except TimeoutError as exc:
            self._interrupt_if_active(attempt, "model turn exceeded the configured time bound")
            raise ModelAttemptError("planning model time bound exceeded") from exc
        except Exception as exc:
            self._interrupt_if_active(attempt, self._safe_reason(exc))
            if isinstance(exc, PlanningConversationError):
                raise
            raise ModelAttemptError("planning model attempt was interrupted") from exc
        return replace(receipt, status=completed.status, turn_version=completed.turn_version)

    async def retry_turn(
        self,
        conversation_id: str,
        turn_id: str,
        *,
        expected_turn_version: int,
    ) -> TurnReceipt:
        """Explicitly start a fresh attempt after interruption and reconciliation."""
        await self.recover(conversation_id)
        turn = self.store.get_turn(conversation_id, turn_id)
        if turn.turn_version != expected_turn_version:
            raise ConversationConflictError("stale learner turn version")
        attempts = self.store.list_attempts(turn_id)
        if not attempts:
            raise ConversationConflictError("retry requires an earlier attempt")
        self._inject("before_retry_cas")
        attempt = self.store.begin_attempt(
            BeginModelAttempt(
                conversation_id,
                turn_id,
                expected_turn_version,
                attempts[-1].attempt_id,
            )
        )
        self._inject("after_retry_cas")
        try:
            async with asyncio.timeout(self.bounds.turn_timeout_seconds):
                completed = await self._execute_attempt(attempt)
        except TimeoutError as exc:
            self._interrupt_if_active(attempt, "model retry exceeded the configured time bound")
            raise ModelAttemptError("planning model time bound exceeded") from exc
        except Exception as exc:
            self._interrupt_if_active(attempt, self._safe_reason(exc))
            if isinstance(exc, PlanningConversationError):
                raise
            raise ModelAttemptError("planning model retry was interrupted") from exc
        refreshed = self.store.get_turn(conversation_id, turn_id)
        return TurnReceipt(
            conversation_id,
            turn_id,
            completed.status,
            completed.turn_version,
            refreshed.brief_context_digest,
            (),
            (),
        )

    async def recover(self, conversation_id: str) -> RecoveryResult:
        """Classify active attempts and reconcile original capability intents."""
        interrupted: list[str] = []
        completed: list[str] = []
        projected: list[str] = []
        refused: list[str] = []
        for intent in self.store.list_unreconciled_capability_intents(conversation_id):
            result = self.store.get_capability_result(intent.intent_id)
            if result is None:
                result = self._dispatch_original_intent(intent)
            if result.status == "projected":
                projected.append(intent.intent_id)
            else:
                refused.append(intent.intent_id)
        for attempt in self.store.active_attempts(conversation_id):
            if self.store.finalized_message_for_attempt(attempt.attempt_id) is not None:
                self.store.complete_attempt(
                    CompleteModelAttempt(
                        conversation_id,
                        attempt.turn_id,
                        attempt.attempt_id,
                        attempt.turn_version,
                    )
                )
                completed.append(attempt.attempt_id)
                continue
            self._inject("before_durable_interruption")
            self.store.mark_attempt_interrupted(
                MarkAttemptInterrupted(
                    conversation_id,
                    attempt.turn_id,
                    attempt.attempt_id,
                    attempt.turn_version,
                    "process recovery found an unfinished provider attempt",
                )
            )
            interrupted.append(attempt.attempt_id)
        return RecoveryResult(
            conversation_id,
            tuple(interrupted),
            tuple(projected),
            tuple(refused),
            tuple(completed),
        )

    async def _execute_attempt(self, attempt: AttemptRecord) -> AttemptRecord:
        turn = self.store.get_turn(attempt.conversation_id, attempt.turn_id)
        request = self.store.load_request(attempt.turn_id)
        scope = PlanningCapabilityScope(
            attempt.conversation_id, attempt.turn_id, attempt.attempt_id
        )
        dispatcher = PlanningCapabilityDispatcher(
            self.lifecycle,
            request,
            scope=scope,
            expected_run_id=turn.planning_run_id,
        )
        expected_run_id = turn.planning_run_id
        messages = self._build_messages(attempt)
        output_parts: list[str] = []
        tool_calls_seen = 0
        for _round in range(1, self.bounds.max_model_rounds + 1):
            self._check_input_bound(messages)
            model_request = ModelRequest(
                MODEL_WIRE_VERSION,
                attempt.conversation_id,
                attempt.turn_id,
                attempt.attempt_id,
                tuple(messages),
                self.bounds.max_output_tokens,
            )
            events = [event async for event in self.model.stream(model_request)]
            calls, completed = self._validate_events(events, attempt, output_parts)
            if calls and completed.finish_reason != "tool_calls":
                raise ModelAttemptError(
                    "planning model tool calls require the tool_calls finish reason"
                )
            if completed.finish_reason == "tool_calls":
                if not calls:
                    raise ModelAttemptError("model requested tools without a typed call")
                assistant_calls: list[dict[str, object]] = []
                tool_messages: list[dict[str, object]] = []
                for call in calls:
                    tool_calls_seen += 1
                    if tool_calls_seen > self.bounds.max_tool_calls:
                        raise ModelAttemptError("planning model tool bound exceeded")
                    try:
                        normalized = normalize_planning_capability_call(
                            PlanningCapabilityCall(call.tool_call_id, call.name, call.arguments),
                            expected_run_id=expected_run_id,
                        )
                    except CapabilityRefusedError as exc:
                        raise ModelAttemptError(self._safe_reason(exc)) from exc
                    call_run_id = normalized.arguments.get("run_id", expected_run_id)
                    run_id = call_run_id if isinstance(call_run_id, str) else expected_run_id
                    key = scope.lifecycle_idempotency_key(
                        run_id=run_id,
                        tool_call_id=normalized.call_id,
                    )
                    self._inject("before_capability_intent_commit")
                    intent = self.store.prepare_capability_call(
                        PrepareCapabilityCall(
                            attempt.conversation_id,
                            attempt.turn_id,
                            attempt.attempt_id,
                            normalized.call_id,
                            normalized.name,
                            normalized.arguments,
                            run_id,
                            key,
                        )
                    )
                    self._inject("after_capability_intent_commit")
                    result = self.store.get_capability_result(intent.intent_id)
                    if result is None:
                        result = self._dispatch_intent(intent, dispatcher)
                    result_run_id = result.payload.get("run_id")
                    if isinstance(result_run_id, str) and result_run_id:
                        expected_run_id = result_run_id
                    assistant_calls.append(
                        {
                            "id": normalized.call_id,
                            "type": "function",
                            "function": {
                                "name": normalized.name,
                                "arguments": json.dumps(
                                    normalized.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                            },
                        }
                    )
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": normalized.call_id,
                            "content": json.dumps(
                                {
                                    "status": result.status,
                                    "payload": result.payload,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        }
                    )
                messages.append({"role": "assistant", "content": "", "tool_calls": assistant_calls})
                messages.extend(tool_messages)
                continue
            if completed.finish_reason in {"length", "error"}:
                raise ModelAttemptError(
                    f"planning model ended with {completed.finish_reason!r} before finalization"
                )
            assistant_text = "".join(output_parts)
            if not assistant_text.strip():
                raise ModelAttemptError("planning model returned no finalized assistant message")
            self._inject("before_finalized_message_commit")
            self.store.finalize_assistant_message(
                FinalizeAssistantMessage(
                    attempt.conversation_id,
                    attempt.turn_id,
                    attempt.attempt_id,
                    assistant_text,
                )
            )
            self._inject("after_finalized_message_commit")
            self._inject("before_attempt_complete")
            completed_attempt = self.store.complete_attempt(
                CompleteModelAttempt(
                    attempt.conversation_id,
                    attempt.turn_id,
                    attempt.attempt_id,
                    attempt.turn_version,
                )
            )
            self._inject("after_attempt_complete")
            return completed_attempt
        raise ModelAttemptError("planning model round bound exceeded")

    def _dispatch_intent(
        self,
        intent,
        dispatcher: PlanningCapabilityDispatcher,
    ) -> StoredCapabilityResult:
        self.store.mark_capability_dispatching(intent.intent_id)
        self._inject("before_lifecycle_dispatch")
        try:
            value = dispatcher.execute(
                PlanningCapabilityCall(
                    intent.tool_call_id,
                    intent.name,
                    intent.arguments,
                    intent.lifecycle_idempotency_key,
                )
            )
            payload = dict(value.payload)
            status = "projected"
        except (CapabilityRefusedError, LifecycleError, PlanningRepositoryError) as exc:
            payload = {"classification": type(exc).__name__, "message": self._safe_reason(exc)}
            status = "refused"
        self._inject("after_lifecycle_dispatch")
        self._inject("before_result_projection")
        result = self.store.project_capability_result(
            ProjectCapabilityResult(intent.intent_id, status, payload)
        )
        self._inject("after_result_projection")
        return result

    def _dispatch_original_intent(self, intent) -> StoredCapabilityResult:
        request = self.store.load_request(intent.turn_id)
        turn = self.store.get_turn(intent.conversation_id, intent.turn_id)
        dispatcher = PlanningCapabilityDispatcher(
            self.lifecycle,
            request,
            scope=PlanningCapabilityScope(
                intent.conversation_id, intent.turn_id, intent.attempt_id
            ),
            expected_run_id=intent.run_id or turn.planning_run_id,
        )
        return self._dispatch_intent(intent, dispatcher)

    def _validate_events(
        self,
        events: list[ModelEvent],
        attempt: AttemptRecord,
        output_parts: list[str],
    ) -> tuple[list[ModelToolCall], ModelTurnCompleted]:
        if not events:
            raise ModelAttemptError("planning model stream ended without a terminal event")
        prior_sequence = 0
        calls: list[ModelToolCall] = []
        completed: ModelTurnCompleted | None = None
        call_ids: set[str] = set()
        for index, event in enumerate(events):
            if (
                event.schema_version != MODEL_WIRE_VERSION
                or event.turn_id != attempt.turn_id
                or event.attempt_id != attempt.attempt_id
                or event.sequence <= prior_sequence
            ):
                raise ModelAttemptError("planning model emitted an invalid ordered event")
            prior_sequence = event.sequence
            if completed is not None:
                raise ModelAttemptError("planning model emitted data after terminal completion")
            if isinstance(event, ModelTextDelta):
                if not isinstance(event.text, str):
                    raise ModelAttemptError("planning model emitted malformed text")
                output_parts.append(self._sanitize(event.text))
                if len("".join(output_parts)) > self.bounds.max_output_characters:
                    raise ModelAttemptError("planning model output bound exceeded")
            elif isinstance(event, ModelToolCall):
                if event.tool_call_id in call_ids:
                    raise ModelAttemptError("planning model duplicated a tool-call ID")
                call_ids.add(event.tool_call_id)
                calls.append(event)
            elif isinstance(event, ModelTurnCompleted):
                if index != len(events) - 1:
                    raise ModelAttemptError("planning model completion was not terminal")
                completed = event
        if completed is None:
            raise ModelAttemptError("planning model stream ended without completion")
        return calls, completed

    def _build_messages(self, attempt: AttemptRecord) -> list[dict[str, object]]:
        prompt = load_architect_prompt()
        messages: list[dict[str, object]] = [
            {"role": "system", "content": prompt.text},
        ]
        assistant_by_turn: dict[str, list[str]] = {}
        for message in self.store.list_messages(attempt.conversation_id):
            assistant_by_turn.setdefault(message.turn_id, []).append(message.content)
        for prior_turn in self.store.list_turns(attempt.conversation_id):
            if prior_turn.turn_id == attempt.turn_id:
                break
            messages.append({"role": "user", "content": self._sanitize(prior_turn.learner_text)})
            messages.extend(
                {"role": "assistant", "content": self._sanitize(content)}
                for content in assistant_by_turn.get(prior_turn.turn_id, [])
            )
        for attachment in self.store.load_context(attempt.turn_id):
            label = self._sanitize_metadata(attachment.label)
            content = self._sanitize(attachment.content)
            messages.append({"role": "user", "content": f"[Tier-four context: {label}]\n{content}"})
        turn = self.store.get_turn(attempt.conversation_id, attempt.turn_id)
        messages.append({"role": "user", "content": self._sanitize(turn.learner_text)})
        for intent, result in self.store.list_capability_history(attempt.turn_id):
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": intent.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": intent.name,
                                "arguments": json.dumps(
                                    intent.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": intent.tool_call_id,
                    "content": self._sanitize(
                        json.dumps(
                            {"status": result.status, "payload": result.payload},
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    ),
                }
            )
        return messages

    def _check_input_bound(self, messages: list[dict[str, object]]) -> None:
        size = sum(len(str(message.get("content", ""))) for message in messages)
        if size > self.bounds.max_input_characters:
            raise ModelAttemptError("planning model input bound exceeded")

    def _sanitize(self, text: str) -> str:
        result = text
        for secret in self._secret_values:
            result = result.replace(secret, _VISIBLE_SECRET_MARKER)
        return result

    def _sanitize_metadata(self, text: str) -> str:
        sanitized = self._sanitize(text)
        if sanitized.startswith(("/", "~", "file://")) or "\\" in sanitized:
            return "selected text context"
        if sanitized.startswith(("http://", "https://")):
            host = urlsplit(sanitized).hostname or ""
            try:
                internal = ip_address(host).is_private or ip_address(host).is_loopback
            except ValueError:
                internal = host.lower() in {"localhost", "localhost.localdomain"}
            if internal:
                return "selected text context"
        return sanitized

    def _safe_reason(self, error: BaseException) -> str:
        if isinstance(
            error,
            (
                PlanningConversationError,
                CapabilityRefusedError,
                LifecycleError,
                PlanningRepositoryError,
            ),
        ):
            return self._sanitize(str(error))[:500] or type(error).__name__
        return type(error).__name__

    def _interrupt_if_active(self, attempt: AttemptRecord, reason: str) -> None:
        active = self.store.active_attempts(attempt.conversation_id)
        if not any(item.attempt_id == attempt.attempt_id for item in active):
            return
        self._inject("before_durable_interruption")
        current = self.store.get_turn(attempt.conversation_id, attempt.turn_id)
        self.store.mark_attempt_interrupted(
            MarkAttemptInterrupted(
                attempt.conversation_id,
                attempt.turn_id,
                attempt.attempt_id,
                current.turn_version,
                reason,
            )
        )

    def _inject(self, point: str) -> None:
        if self._crash_injector is not None:
            self._crash_injector(point)
