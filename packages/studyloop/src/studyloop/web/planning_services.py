"""Shared injectable service bundle for the browser planning vertical slice."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from studyloop.planning.context_ingestion import PlanningContextIngestor
from studyloop.planning.conversation_decisions import ConversationDecisionAdapter
from studyloop.planning.conversation_runtime import PlanningConversationRuntime
from studyloop.planning.model_config import profile_from_config
from studyloop.planning.openai_compatible import OpenAICompatiblePlanningModel
from studyloop.planning.repository import MAX_CURRENT_PLANS
from studyloop.planning.runtime import planning_conversation_store, planning_lifecycle
from studyloop.settings import load_raw_config

if TYPE_CHECKING:
    from studyloop.planning.conversation_contracts import TurnReceipt
    from studyloop.planning.conversation_store import ConversationStore
    from studyloop.planning.lifecycle import PlanningLifecycle


@dataclass(slots=True)
class PlanningServices:
    store: ConversationStore
    lifecycle: PlanningLifecycle
    runtime: PlanningConversationRuntime | None
    context: PlanningContextIngestor
    decisions: ConversationDecisionAdapter
    tasks: dict[str, asyncio.Task[object]] = field(default_factory=dict)

    def capacity(self) -> dict[str, int | bool]:
        current = self.lifecycle.repository.project(
            lambda snapshot, _events: snapshot.current_count
        )
        return {
            "current": current,
            "max": MAX_CURRENT_PLANS,
            "available": max(0, MAX_CURRENT_PLANS - current),
            "can_create": current < MAX_CURRENT_PLANS,
        }

    def schedule_turn(self, receipt: TurnReceipt) -> None:
        if self.runtime is None:
            raise RuntimeError("planning model is not configured")
        self._schedule(
            receipt.conversation_id,
            self.runtime.run_captured_turn(receipt),
            name=f"planning-turn:{receipt.turn_id}",
        )

    def schedule_retry(self, conversation_id: str, turn_id: str, turn_version: int) -> None:
        if self.runtime is None:
            raise RuntimeError("planning model is not configured")
        self._schedule(
            conversation_id,
            self.runtime.retry_turn(
                conversation_id,
                turn_id,
                expected_turn_version=turn_version,
            ),
            name=f"planning-retry:{turn_id}",
        )

    def _schedule(self, conversation_id: str, awaitable: object, *, name: str) -> None:
        task = asyncio.create_task(awaitable, name=name)  # type: ignore[arg-type]
        self.tasks[conversation_id] = task

        def finished(done: asyncio.Task[object]) -> None:
            self.tasks.pop(conversation_id, None)
            if not done.cancelled():
                _ = done.exception()

        task.add_done_callback(finished)

    async def stop(self, conversation_id: str) -> bool:
        task = self.tasks.get(conversation_id)
        if task is None or task.done():
            return False
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return True

    async def shutdown(self) -> None:
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


def create_planning_services(*, model: object | None = None) -> PlanningServices:
    """Build one store/runtime/lifecycle graph; tests may inject the model port."""
    store = planning_conversation_store()
    lifecycle = planning_lifecycle()
    selected_model = model
    if selected_model is None:
        raw = load_raw_config()
        planning = raw.get("planning") if isinstance(raw, dict) else None
        configured = planning.get("model") if isinstance(planning, dict) else None
        profile = profile_from_config(configured)
        selected_model = OpenAICompatiblePlanningModel(profile) if profile is not None else None
    runtime = (
        PlanningConversationRuntime(store, selected_model, lifecycle)  # type: ignore[arg-type]
        if selected_model is not None
        else None
    )
    return PlanningServices(
        store,
        lifecycle,
        runtime,
        PlanningContextIngestor(store),
        ConversationDecisionAdapter(store, lifecycle),
    )


__all__ = ["PlanningServices", "create_planning_services"]
