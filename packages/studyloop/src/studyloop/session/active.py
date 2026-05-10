"""Active session primitive — module-level singleton with an asyncio.Lock.

Holds *the* currently-running agent session. One process, one session:
the plan's single-session invariant (one learner, one agent, one PTY)
is enforced here, atomically, so the web route and CLI cannot race each
other into a double-start.

Why a module, not a class: the architecture review wanted an atomic home
for the "is something running?" check; the simplicity review objected to
class ceremony for a singleton. The compromise is a module with a lock —
no `StudySessionManager` class, no `app.state` wiring, just three small
async functions.

See docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.4.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from studyloop import session_state
from studyloop.session.transport import (
    AgentSessionTransport,
    SessionAlreadyActiveError,
    SessionConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class ActiveSession:
    """The currently-live session. Returned by ``acquire`` / ``current``."""

    study_session_id: str
    transport: AgentSessionTransport
    config: SessionConfig


_lock = asyncio.Lock()
_active: ActiveSession | None = None


async def acquire(
    config: SessionConfig,
    transport_factory: Callable[[], AgentSessionTransport],
) -> ActiveSession:
    """Reserve the single-session slot and start the transport.

    Atomic under ``_lock`` — the reservation, transport.start(), and slot
    assignment all happen without yielding to another acquire task, so two
    concurrent calls cannot both observe an empty slot and both install.

    If ``transport.start()`` raises, the slot stays empty so the next
    caller can try again.

    Raises:
        SessionAlreadyActiveError: a session is already active.
        FileNotFoundError / OSError: propagated from ``transport.start``.
    """
    global _active
    async with _lock:
        if _active is not None:
            raise SessionAlreadyActiveError(f"Session {_active.study_session_id} already active")
        transport = transport_factory()
        await transport.start(config)
        _active = ActiveSession(
            study_session_id=config.study_session_id,
            transport=transport,
            config=config,
        )

    # session_state.write_session_state() takes an fcntl.flock on a lock
    # file and would block the event loop. Run off-thread (plan B7).
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        session_state.write_session_state,
        {
            "study_session_id": config.study_session_id,
            "agent": config.agent,
        },
    )
    logger.info(
        "active session acquired id=%s agent=%s",
        config.study_session_id,
        config.agent,
    )
    return _active


async def current() -> ActiveSession | None:
    """Return the active session, or None if nothing is running.

    Pointer read; no lock needed. Callers that act on the result should
    either tolerate the session ending between ``current()`` and the
    action, or go through ``release()`` for synchronised teardown.
    """
    return _active


async def release() -> None:
    """End the active transport and clear the slot. Idempotent.

    Safe to call when nothing is active — returns silently. Never raises
    if the transport's ``end()`` raises; the slot is always cleared so a
    stuck transport can't wedge the singleton permanently.
    """
    global _active
    async with _lock:
        if _active is None:
            return
        session = _active
        _active = None

    try:
        await session.transport.end()
    except Exception:
        logger.exception(
            "transport.end() raised for session %s; slot cleared anyway",
            session.study_session_id,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, session_state.clear_session_files)
    logger.info("active session released id=%s", session.study_session_id)
