"""Bounded application service for durable, confined planning conversations."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING

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
from .conversation_store import _safe_context_label
from .model_port import (
    MODEL_WIRE_VERSION,
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
        owner_id: str | None = None,
        lease_heartbeat_seconds: float | None = None,
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
        self._owner_id = owner_id or f"conversation-runtime-{uuid.uuid4().hex}"
        default_heartbeat = self.store.attempt_lease_seconds / 3
        self._lease_heartbeat_seconds = (
            default_heartbeat if lease_heartbeat_seconds is None else lease_heartbeat_seconds
        )
        if not 0 < self._lease_heartbeat_seconds < self.store.attempt_lease_seconds:
            raise ValueError("attempt heartbeat must be shorter than the durable lease")

    async def accept_turn(self, conversation_id: str, turn: LearnerTurn) -> TurnReceipt:
        """Durably capture a turn, then run exactly one bounded model attempt."""
        receipt = self.capture_turn(conversation_id, turn)
        return await self.run_captured_turn(receipt)

    def capture_turn(self, conversation_id: str, turn: LearnerTurn) -> TurnReceipt:
        """Persist the exact learner input before an adapter schedules model work."""
        return self.store.capture_turn_and_freeze_context(CaptureLearnerTurn(conversation_id, turn))

    async def run_captured_turn(self, receipt: TurnReceipt) -> TurnReceipt:
        """Run a previously captured turn without accepting a second input shape."""
        if receipt.status == "completed":
            return receipt
        if receipt.status != "ready":
            raise ConversationConflictError("learner turn is already scheduled or retryable")
        attempt = self.store.begin_attempt(
            BeginModelAttempt(
                receipt.conversation_id,
                receipt.turn_id,
                receipt.turn_version,
                None,
                self._owner_id,
            )
        )
        completed = await self._run_attempt_safely(attempt, retry=False)
        return replace(receipt, status=completed.status, turn_version=completed.turn_version)

    async def retry_turn(
        self,
        conversation_id: str,
        turn_id: str,
        *,
        expected_turn_version: int,
    ) -> TurnReceipt:
        """Explicitly start a fresh attempt after interruption and reconciliation."""
        turn = self.store.get_turn(conversation_id, turn_id)
        if turn.turn_version != expected_turn_version:
            raise ConversationConflictError("stale learner turn version")
        attempts = self.store.list_attempts(turn_id)
        if not attempts or turn.status != "retryable" or attempts[-1].status != "interrupted":
            raise ConversationConflictError("retry requires an already durably interrupted attempt")
        self._inject("before_retry_cas")
        attempt = self.store.begin_attempt(
            BeginModelAttempt(
                conversation_id,
                turn_id,
                expected_turn_version,
                attempts[-1].attempt_id,
                self._owner_id,
            )
        )
        self._inject("after_retry_cas")
        completed = await self._run_attempt_safely(attempt, retry=True)
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

    async def _run_attempt_safely(
        self,
        attempt: AttemptRecord,
        *,
        retry: bool,
    ) -> AttemptRecord:
        public_error: PlanningConversationError | None = None
        cancelled: asyncio.CancelledError | None = None
        completed: AttemptRecord | None = None
        try:
            completed = await self._run_with_lease(attempt)
        except asyncio.CancelledError:
            self._settle_from_durable_truth(attempt, "model attempt was cancelled")
            cancelled = asyncio.CancelledError()
        except TimeoutError:
            reason = (
                "model retry exceeded the configured time bound"
                if retry
                else ("model turn exceeded the configured time bound")
            )
            self._settle_from_durable_truth(attempt, reason)
            public_error = ModelAttemptError("planning model time bound exceeded")
        except Exception as exc:
            self._settle_from_durable_truth(attempt, self._safe_reason(exc))
            if isinstance(exc, ConversationConflictError):
                public_error = ConversationConflictError(self._safe_reason(exc))
            elif isinstance(exc, PlanningConversationError):
                public_error = ModelAttemptError(self._safe_reason(exc))
            else:
                public_error = ModelAttemptError("planning model attempt was interrupted")
        if cancelled is not None:
            raise cancelled
        if public_error is not None:
            raise public_error
        if completed is None:  # pragma: no cover - exhaustive terminal branches above
            raise ModelAttemptError("planning model attempt ended without durable truth")
        return completed

    async def _run_with_lease(self, attempt: AttemptRecord) -> AttemptRecord:
        owner_task = asyncio.current_task()
        if owner_task is None:  # pragma: no cover - async entry always owns a task
            raise ModelAttemptError("planning model attempt has no task owner")
        heartbeat = asyncio.create_task(self._heartbeat_attempt(attempt, owner_task))
        try:
            async with asyncio.timeout(self.bounds.turn_timeout_seconds):
                return await self._execute_attempt(attempt)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_attempt(
        self,
        attempt: AttemptRecord,
        owner_task: asyncio.Task[object],
    ) -> None:
        while True:
            await asyncio.sleep(self._lease_heartbeat_seconds)
            try:
                attempt = self.store.renew_attempt_lease(attempt, self._owner_id)
            except ConversationConflictError:
                owner_task.cancel()
                return

    async def recover(self, conversation_id: str) -> RecoveryResult:
        """Claim expired attempts, then reconcile only provably orphaned work."""
        interrupted: list[str] = []
        completed: list[str] = []
        projected: list[str] = []
        refused: list[str] = []
        claimed: list[AttemptRecord] = []
        for candidate in self.store.recoverable_attempts(conversation_id):
            recovered = self.store.claim_expired_attempt(candidate, self._owner_id)
            if recovered is not None:
                claimed.append(recovered)
        owner_task = asyncio.current_task()
        if owner_task is None:  # pragma: no cover - async entry always owns a task
            raise ModelAttemptError("planning recovery has no task owner")
        heartbeats = [
            asyncio.create_task(self._heartbeat_attempt(attempt, owner_task)) for attempt in claimed
        ]
        try:
            active_ids = {
                attempt.attempt_id for attempt in self.store.active_attempts(conversation_id)
            }
            claimed_ids = {attempt.attempt_id for attempt in claimed}
            for intent in self.store.list_unreconciled_capability_intents(conversation_id):
                if intent.attempt_id in active_ids and intent.attempt_id not in claimed_ids:
                    continue
                result = self.store.get_capability_result(intent.intent_id)
                if result is None:
                    result = await asyncio.to_thread(self._dispatch_original_intent, intent)
                if result.status == "projected":
                    projected.append(intent.intent_id)
                else:
                    refused.append(intent.intent_id)
            for attempt in claimed:
                if self.store.finalized_message_for_attempt(attempt.attempt_id) is not None:
                    self.store.complete_attempt(
                        CompleteModelAttempt(
                            conversation_id,
                            attempt.turn_id,
                            attempt.attempt_id,
                            attempt.turn_version,
                            self._owner_id,
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
                        self._owner_id,
                    )
                )
                interrupted.append(attempt.attempt_id)
        finally:
            for heartbeat in heartbeats:
                heartbeat.cancel()
            for heartbeat in heartbeats:
                with suppress(asyncio.CancelledError):
                    await heartbeat
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
        output_characters = 0
        tool_calls_seen = 0
        model_events_seen = 0
        for _round in range(1, self.bounds.max_model_rounds + 1):
            self._check_input_bound(messages)
            model_request = ModelRequest(
                MODEL_WIRE_VERSION,
                attempt.conversation_id,
                attempt.turn_id,
                attempt.attempt_id,
                tuple(messages),
                self.bounds.max_output_tokens,
                self.bounds.max_output_characters,
                self.bounds.max_model_events,
                self.bounds.max_tool_calls,
                self.bounds.max_tool_name_characters,
                self.bounds.max_tool_argument_characters,
            )
            (
                calls,
                completed,
                model_events_seen,
                output_characters,
            ) = await self._consume_model_events(
                model_request,
                attempt,
                output_parts,
                events_seen=model_events_seen,
                output_characters=output_characters,
                tool_calls_seen=tool_calls_seen,
            )
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
                            self._owner_id,
                        )
                    )
                    self._inject("after_capability_intent_commit")
                    result = self.store.get_capability_result(intent.intent_id)
                    if result is None:
                        result = await asyncio.to_thread(
                            self._dispatch_intent,
                            intent,
                            dispatcher,
                        )
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
                    self._owner_id,
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
                    self._owner_id,
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
        self.store.mark_capability_dispatching(intent.intent_id, self._owner_id)
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
            ProjectCapabilityResult(
                intent.intent_id,
                status,
                payload,
                self._owner_id,
            )
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

    async def _consume_model_events(
        self,
        request: ModelRequest,
        attempt: AttemptRecord,
        output_parts: list[str],
        *,
        events_seen: int,
        output_characters: int,
        tool_calls_seen: int,
    ) -> tuple[list[ModelToolCall], ModelTurnCompleted, int, int]:
        prior_sequence = 0
        calls: list[ModelToolCall] = []
        completed: ModelTurnCompleted | None = None
        call_ids: set[str] = set()
        stream = self.model.stream(request)
        try:
            async for event in stream:
                events_seen += 1
                if events_seen > self.bounds.max_model_events:
                    raise ModelAttemptError("planning model event bound exceeded")
                if completed is not None:
                    raise ModelAttemptError("planning model emitted data after terminal completion")
                if (
                    not isinstance(event, (ModelTextDelta, ModelToolCall, ModelTurnCompleted))
                    or event.schema_version != MODEL_WIRE_VERSION
                    or event.turn_id != attempt.turn_id
                    or event.attempt_id != attempt.attempt_id
                    or event.sequence <= prior_sequence
                ):
                    raise ModelAttemptError("planning model emitted an invalid ordered event")
                prior_sequence = event.sequence
                if isinstance(event, ModelTextDelta):
                    if not isinstance(event.text, str):
                        raise ModelAttemptError("planning model emitted malformed text")
                    text = self._sanitize(event.text)
                    output_characters += len(text)
                    if output_characters > self.bounds.max_output_characters:
                        raise ModelAttemptError("planning model output bound exceeded")
                    output_parts.append(text)
                elif isinstance(event, ModelToolCall):
                    if tool_calls_seen + len(calls) + 1 > self.bounds.max_tool_calls:
                        raise ModelAttemptError("planning model tool bound exceeded")
                    if event.tool_call_id in call_ids:
                        raise ModelAttemptError("planning model duplicated a tool-call ID")
                    if (
                        len(event.tool_call_id) > self.bounds.max_tool_name_characters
                        or len(event.name) > self.bounds.max_tool_name_characters
                    ):
                        raise ModelAttemptError("planning model tool name bound exceeded")
                    try:
                        argument_size = len(
                            json.dumps(
                                event.arguments,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                        )
                    except (TypeError, ValueError) as exc:
                        raise ModelAttemptError(
                            "planning model emitted malformed tool arguments"
                        ) from exc
                    if argument_size > self.bounds.max_tool_argument_characters:
                        raise ModelAttemptError("planning model tool argument bound exceeded")
                    call_ids.add(event.tool_call_id)
                    calls.append(event)
                else:
                    completed = event
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                with suppress(Exception):
                    await close()
        if completed is None:
            raise ModelAttemptError("planning model stream ended without completion")
        return calls, completed, events_seen, output_characters

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
        try:
            size = len(
                json.dumps(
                    messages,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ModelAttemptError("planning model input is not serializable") from exc
        if size > self.bounds.max_input_characters:
            raise ModelAttemptError("planning model input bound exceeded")

    def _sanitize(self, text: str) -> str:
        result = text
        for secret in self._secret_values:
            result = result.replace(secret, _VISIBLE_SECRET_MARKER)
        return result

    def _sanitize_metadata(self, text: str) -> str:
        return _safe_context_label(self._sanitize(text))

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
            sanitized = self._sanitize_metadata(str(error))[:500]
            if sanitized == "selected text context":
                return "planning runtime detail redacted"
            return sanitized or type(error).__name__
        return type(error).__name__

    def _settle_from_durable_truth(self, attempt: AttemptRecord, reason: str) -> None:
        active = self.store.active_attempts(attempt.conversation_id)
        current = next(
            (item for item in active if item.attempt_id == attempt.attempt_id),
            None,
        )
        if current is None or current.owner_id != self._owner_id:
            return
        if self.store.finalized_message_for_attempt(attempt.attempt_id) is not None:
            self.store.complete_attempt(
                CompleteModelAttempt(
                    attempt.conversation_id,
                    attempt.turn_id,
                    attempt.attempt_id,
                    current.turn_version,
                    self._owner_id,
                )
            )
            return
        self._inject("before_durable_interruption")
        self.store.mark_attempt_interrupted(
            MarkAttemptInterrupted(
                attempt.conversation_id,
                attempt.turn_id,
                attempt.attempt_id,
                current.turn_version,
                reason,
                self._owner_id,
            )
        )

    def _inject(self, point: str) -> None:
        if self._crash_injector is not None:
            self._crash_injector(point)
