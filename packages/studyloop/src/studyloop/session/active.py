"""Active session primitive — module-level singleton with an asyncio.Lock.

Holds *the* currently-running WEB PTY/ACP agent session, IN THIS PROCESS
ONLY. It is a CACHE of the cross-process claim recorded in
``session-state.json`` (``session_state.py``), not the claim itself — see
docs/architecture/session-authority.md for the full contract. Two starts
racing each other *within this process* (two concurrent
``POST /api/session/start`` calls) are serialised here, atomically, under
one ``asyncio.Lock``.

What this module does NOT do (an earlier version of this docstring implied
it did, which R-01 named as the exact gap that let a web start silently
clobber a live CLI session): it has no idea a CLI-owned session
(``studyloop study``, which never touches this module) exists at all. The
web start routes (``web/routes/session/_start.py``) are what cross-checks
this singleton against the file claim before deciding whether to acquire —
this module only serialises acquisition once that decision has already
been made.

Why a module, not a class: the architecture review wanted an atomic home
for the "is something running in THIS process?" check; the simplicity
review objected to class ceremony for a singleton. The compromise is a
module with a lock — no `StudySessionManager` class, no `app.state`
wiring, just three small async functions.

See private-docs/2026-05-09-refactor-agent-session-transport-plan.md §1.4.
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
    await loop.run_in_executor(None, _clear_files_of, session.study_session_id)
    logger.info("active session released id=%s", session.study_session_id)


def _clear_files_of(study_session_id: str) -> None:
    """Clear the IPC files the released session owned -- and only those.

    Until review 2026-10-21 (plan 5, larger #1) this was an unconditional
    ``clear_session_files()``, which deleted files the released session did not
    own in two ways. The state file names its owner, so read it first:

    - **Another session's.** The reaper releases a slot whose state file no
      longer names it (``state_file_replaced``: a later start has written its
      claim, and its topics and parking files are its own). Nothing here is
      that session's to delete; touch nothing.
    - **Ours, saved.** Every end path writes ``mode=ended`` after persisting
      the session (``cleanup.persist_session_end``), and the dashboard's
      summary view renders from that file. Deleting it here is why a browser
      session never showed its summary. Keep the state file; the topics and
      parking files have been persisted and go. An ended claim blocks no
      start (``_claim_exists``), and the next start replaces the file.
    - **Ours, unsaved** (no ``mode=ended``: the marker write failed, or a
      caller released without ending) and **nobody's** (no id): as before,
      everything goes. A kept file would read as a live claim owned by this
      process's pid and refuse the next ``studyloop study``, and there is no
      saved summary for it to show. The marker is NOT written here: it means
      "persisted", and only the code that persisted may say so.

    Runs on an executor thread (``write_session_state``'s flock would block the
    loop). Reading, then unlinking, is not atomic against a start landing in
    between on the loop; that window is the read-to-unlink gap of the unsaved
    case only, where it used to be the whole release.
    """
    state = session_state.read_session_state()
    owner = state.get("study_session_id")
    if owner and owner != study_session_id:
        return
    session_state.clear_session_files(keep_state=bool(owner) and state.get("mode") == "ended")
