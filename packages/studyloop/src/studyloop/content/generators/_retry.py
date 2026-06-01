"""Retry-with-correction loop shared by HTTP-backed generator adapters.

Both OpenAI Chat Completions and Anthropic Messages return a
tool-call payload that we then ``model_validate`` against the deck
pydantic model. If validation fails, we don't bail -- we feed the
validation error back to the model as a correction turn so it can
self-repair the JSON. After ``max_retries`` failures we surface
:class:`CardGenerationError`.

This shape exists in :class:`BedrockGenerator` (`bedrock.py:_generate`)
verbatim. The HTTP adapters share it via this helper rather than
duplicating the loop. Bedrock keeps its own copy because Converse's
message-history shape is sufficiently different that the abstraction
boundary would leak details for no real win.

Why not async
-------------

The runner is thread-pool, not asyncio. Both ``httpx`` and the deck
model_validate are sync. Keeping this helper sync means it composes
trivially with the existing :func:`generate_concurrently` flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from studyloop.content.generators import CardGenerationError

if TYPE_CHECKING:
    from collections.abc import Callable


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class CallContext[T: BaseModel]:
    """Per-attempt context handed to the adapter's call function.

    Why a context object: the call function needs to thread a growing
    message history (so the model sees its previous bad reply + our
    correction note) plus a one-shot ``last_error`` string for the
    correction turn. Bundling them keeps adapter ``call_fn`` signatures
    stable across attempts without spreading kwargs.
    """

    attempt: int
    last_error: str | None
    history_extension: list[dict[str, Any]]


def call_with_correction[T: BaseModel](
    *,
    model_cls: type[T],
    max_retries: int,
    call_fn: Callable[[CallContext[T]], tuple[Any, list[dict[str, Any]]]],
) -> T:
    """Run ``call_fn`` until it returns a payload that validates as ``model_cls``.

    Args:
        model_cls: The pydantic deck model the payload must match.
        max_retries: Number of *retries* (so total attempts = max_retries + 1).
        call_fn: Per-attempt callable that returns
            ``(tool_payload, history_extension)`` -- the raw dict from the
            tool-call and the message turns to append for any next attempt
            (typically the assistant's bad reply). The helper appends the
            user-side correction turn itself if validation fails.

    Returns:
        The validated deck.

    Raises:
        CardGenerationError: After ``max_retries`` consecutive validation
            failures, with the *last* validation error in the message.
    """
    history_extension: list[dict[str, Any]] = []
    last_error: str | None = None
    last_transient: CardGenerationError | None = None

    for attempt in range(max_retries + 1):
        ctx = CallContext[T](
            attempt=attempt,
            last_error=last_error,
            history_extension=history_extension,
        )
        try:
            tool_payload, new_history = call_fn(ctx)
        except CardGenerationError as exc:
            # Transient call failure (e.g. a flaky provider returned an
            # unparseable / tool-less response, or a momentary transport blip).
            # Don't hard-fail the whole generation on a single bad emission —
            # retry within the same budget. Some providers (MiniMax M2.7) only
            # emit a valid tool call ~half the time, so one clean retry usually
            # succeeds. The history is left unchanged (the bad turn is dropped).
            last_transient = exc
            last_error = f"Previous attempt failed to produce a usable tool call: {exc}"
            continue

        last_transient = None
        history_extension = new_history

        try:
            return model_cls.model_validate(tool_payload)
        except ValidationError as exc:
            last_error = f"Tool input did not match schema: {exc.errors()!r}"

    # Exhausted the budget. If the last failure was a transient call error,
    # surface that (it's more actionable than a stale schema error).
    if last_transient is not None:
        raise CardGenerationError(
            f"Generator failed to produce a usable tool call after "
            f"{max_retries + 1} attempts: {last_transient}"
        )
    raise CardGenerationError(
        f"Generator returned invalid payload after {max_retries + 1} attempts: {last_error}"
    )


__all__ = ["CallContext", "call_with_correction"]
