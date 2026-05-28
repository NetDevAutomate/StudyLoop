"""Active-generation primitive — module-level singleton with an asyncio.Lock.

Holds *the* currently-running content-generation job. One process, one
generation: only one heavy LLM run can be in-flight at a time so two
concurrent clicks of "Generate" don't trash the local Ollama or burn
duplicate provider quota.

Mirrors :mod:`studyloop.session.active` deliberately — same lock
pattern, same idempotent-release semantics. The two are sister
singletons: one for "the live agent session", one for "the live
generation job". Reading them side-by-side should feel obvious.

Differences from session/active.py:

- No filesystem state file. Generation jobs are per-process and
  short-lived; cross-process discovery is overkill.
- No ``transport`` field. The job task owns its generator instance
  directly; the singleton just holds the descriptor of what's running
  for the WS layer to look up.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GenerationAlreadyActiveError(RuntimeError):
    """Raised when a second generation tries to acquire while one is live."""


@dataclass
class ActiveGeneration:
    """The currently-live generation job. Returned by ``acquire`` / ``current``."""

    job_id: str
    request: object  # GenerateRequest from U5; typed as object to avoid coupling.
    started_at: datetime
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


_lock = asyncio.Lock()
_active: ActiveGeneration | None = None


async def acquire(job_id: str, request: object) -> ActiveGeneration:
    """Reserve the single-generation slot.

    Atomic under ``_lock`` — the slot check and assignment happen
    without yielding to another acquire task.

    Args:
        job_id: Caller-generated id (e.g. ``"gen-7c3f1a8b"``). Used by
            the WS layer to route progress events.
        request: The validated request body. Stored as ``object`` to
            avoid pulling the U5 pydantic model into this module's
            import surface; callers cast back to the concrete type.

    Raises:
        GenerationAlreadyActiveError: a generation is already active.
    """
    global _active
    async with _lock:
        if _active is not None:
            raise GenerationAlreadyActiveError(
                f"Generation {_active.job_id} already active; only one job at a time."
            )
        _active = ActiveGeneration(
            job_id=job_id,
            request=request,
            started_at=datetime.now(UTC),
        )
    logger.info("active generation acquired job_id=%s", job_id)
    return _active


async def current() -> ActiveGeneration | None:
    """Return the active generation, or None.

    Pointer read; no lock needed. Callers acting on the result should
    tolerate the job ending between ``current()`` and the action, or go
    through ``release()`` for synchronised teardown.
    """
    return _active


async def release() -> None:
    """Clear the slot. Idempotent.

    Safe to call when nothing is active — returns silently. The
    contract mirrors :func:`studyloop.session.active.release`: the slot
    is *always* cleared so a stuck job can't wedge the singleton.
    """
    global _active
    async with _lock:
        if _active is None:
            return
        job = _active
        _active = None
    logger.info("active generation released job_id=%s", job.job_id)


__all__ = [
    "ActiveGeneration",
    "GenerationAlreadyActiveError",
    "acquire",
    "current",
    "release",
]
