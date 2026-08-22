"""Detach grace period + single-attach bookkeeping for ``/session/ws``.

Why this exists
---------------
A browser refresh closes the session WebSocket. Releasing the active session
on that close kills the agent child (``transport.end()``) and wipes the IPC
state, so an accidental ⌘R used to destroy a live mentoring session outright.
See ``docs/handoffs/2026-08-04-ws-refresh-destroys-session-handoff.md``.

The transport already supports reattaching: ``events()`` is a thin drain over
an ``asyncio.Queue`` that a WebSocket-independent reader task fills, and that
queue is bounded with drop-oldest, so a detached session has bounded memory
and never blocks the agent. What was missing is lifecycle: somewhere to hold
the session between "client went away" and "client came back".

This module is that somewhere. It owns two pieces of process-global state, a
small audit record, and a backstop task:

``_pending``
    A deferred ``active.release()`` per session id, cancellable by a
    reconnect inside the grace window. The timer *polls* transport liveness
    rather than sleeping blind, because a detached session has no consumer
    draining ``events()`` and therefore cannot observe ``Stopped``; without
    the poll, an agent that exits while detached would pin the
    single-session slot for the whole window.

``_attachment``
    Which WebSocket currently consumes the session's event stream. Needed
    because ``transport.events()`` is a *drain*: each event goes to exactly one
    consumer, so two attached sockets each receive a random subset and both
    terminals show partial, interleaved output. The slot is therefore
    single-entry, newest-wins, and scoped to the *session* rather than to a
    socket handler's ``finally`` — see the Consumer slot section below for the
    measurements behind that choice.

``_last_release``
    Why the most recent session went away. A session released on grace expiry
    leaves no trace in the UI otherwise, and "my session vanished" needs to be
    explainable. Read by ``/api/session/state`` when nothing is active.

``_reaper``
    The backstop for every way a slot can be pinned that ``_pending`` cannot
    see, because ``schedule_release`` only ever runs from a WebSocket *close*:
    a session whose socket never attached at all, and a session ended or
    cleaned from another process. See the Slot reaper section below.

Process-global (module-level) rather than ``app.state`` to match
``session/active.py``: there is one learner, one agent, one PTY per process,
and the active-session singleton this cooperates with is already a module.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from studyloop.session.transport import AgentSessionTransport

logger = logging.getLogger(__name__)

#: How long a session survives with no WebSocket attached.
#:
#: 90 s is long enough for a slow reload, a browser restart, or walking to
#: another device; short enough that an abandoned tab does not pin the
#: single-session slot for long. Deliberately not a user-facing setting —
#: one more knob in ``config.yaml`` is not worth the surface.
#:
#: ``STUDYLOOP_WS_GRACE_SECONDS`` overrides it. That exists so out-of-process
#: tests can exercise expiry in seconds rather than 90 (and so a support
#: session can shorten it), not as a documented feature. Invalid or
#: non-positive values fall back to the constant.
GRACE_SECONDS = 90.0

_GRACE_ENV = "STUDYLOOP_WS_GRACE_SECONDS"


def _grace_from_env() -> float:
    raw = os.environ.get(_GRACE_ENV, "").strip()
    if not raw:
        return GRACE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("ignoring invalid %s=%r", _GRACE_ENV, raw)
        return GRACE_SECONDS
    if value <= 0:
        logger.warning("ignoring non-positive %s=%r", _GRACE_ENV, raw)
        return GRACE_SECONDS
    return value


#: How often the grace timer re-checks that the agent is still alive.
POLL_SECONDS = 0.5

#: How often the slot reaper re-checks the active session. Cheap — a pointer
#: read, a liveness probe, and one small file read — so a short interval costs
#: nothing and keeps "I ended it in a terminal" feeling immediate.
REAP_INTERVAL_SECONDS = 5.0

#: Env override for the reaper interval, in seconds.
#:
#: Exists for the same reason ``STUDYLOOP_WS_GRACE_SECONDS`` does: a test that
#: shortens the detach window to a few seconds leaves the reaper ticking at the
#: production 5 s, so the window always expires first and the reaper's
#: "the agent is gone" branch can never be observed. The release is then always
#: recorded as ``grace_expired``, never ``agent_exited`` — not because the code
#: is wrong, but because the test gave it no tick to fire in. Shortening one
#: clock without the other is exactly the hazard ``UNATTACHED_GRACE_SECONDS``
#: warns about above.
_REAP_ENV = "STUDYLOOP_REAP_INTERVAL_SECONDS"

#: How long a session must have held the slot before the reaper will believe
#: the IPC state file about it.
#:
#: ``active.acquire()`` fills the slot *inside* its lock and writes the state
#: file afterwards, off-thread. There is therefore a brief, legitimate window
#: where the slot is occupied and the file is not yet written. Reaping inside
#: that window would kill sessions a fraction of a second after the learner
#: started them — strictly worse than the bug this reaper exists to fix.
RECONCILE_MIN_AGE_SECONDS = 5.0

#: How long a session may hold the slot with no WebSocket having *ever*
#: attached to it.
#:
#: Deliberately a separate constant from ``GRACE_SECONDS`` (and a separate env
#: override) even though the default matches. The detach window is about a
#: learner coming back; this one is about a client that never arrived — a
#: refused origin check, a proxy that ate the upgrade, a JS error before mount.
#: Tests that shorten the detach window to exercise expiry must not
#: accidentally shorten this one and reap sessions they are still using.
UNATTACHED_GRACE_SECONDS = 90.0

_UNATTACHED_ENV = "STUDYLOOP_UNATTACHED_GRACE_SECONDS"


def _unattached_grace_from_env() -> float:
    raw = os.environ.get(_UNATTACHED_ENV, "").strip()
    if not raw:
        return UNATTACHED_GRACE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("ignoring invalid %s=%r", _UNATTACHED_ENV, raw)
        return UNATTACHED_GRACE_SECONDS
    if value <= 0:
        logger.warning("ignoring non-positive %s=%r", _UNATTACHED_ENV, raw)
        return UNATTACHED_GRACE_SECONDS
    return value


_pending: dict[str, asyncio.Task[None]] = {}
_last_release: dict[str, Any] | None = None

#: When the reaper first observed each session id, and which ids have ever had
#: a WebSocket consumer. Both are reaper bookkeeping: touched only from the
#: event loop thread (plus ``reset_for_tests``), so neither needs a lock.
_first_seen: dict[str, float] = {}
_ever_attached: set[str] = set()

_reaper: asyncio.Task[None] | None = None


@runtime_checkable
class _LivenessProbe(Protocol):
    """Duck-typed ``is_running()``.

    Not on ``AgentSessionTransport``: adding it there would fail structural
    checks for transports that do not implement it (the same reasoning as
    ``_PermissionResponder`` in ``_transport.py``). A transport without the
    method is assumed alive, which degrades to the plain-sleep behaviour.
    """

    def is_running(self) -> bool: ...


# --- Consumer slot -----------------------------------------------------------
#
# One consumer at a time, and the *newest* one wins.
#
# The handover recommended refusing a second attach so the learner is told why
# their new tab is empty. Measurement changed the answer. Refusing means the
# slot's lifetime is tied to a socket handler's ``finally``, and two things then
# go wrong, both observed:
#
#   * A reload's reattach can reach ``attach()`` before the old socket's handler
#     has run, and is refused with a handshake 403 — the learner keeps a live
#     agent they can no longer talk to, which is worse than the original defect
#     because nothing explains it.
#   * A half-open socket (closed laptop lid, phone off wifi) is not noticed by
#     the server for minutes, so reopening the dashboard *anywhere* is refused
#     for that whole time. The session is alive and unreachable.
#
# Takeover fixes both and keeps the property that actually matters — never two
# consumers draining ``events()`` at once, which would split the output. The
# displaced socket is told why on its own connection, so the explanation the
# handover wanted is preserved; it just lands on the tab that lost.


@dataclass
class Attachment:
    """One WebSocket's claim on a session's event stream.

    Identity matters: a handler must only ever release *its own* claim. The old
    "clear the global slot in finally" shape let a slow handler clobber the
    claim of the socket that replaced it, which is the 403-on-next-session race.

    ``superseded`` is a plain bool, polled by the holder, not an
    ``asyncio.Event``: an Event binds to whichever loop first awaits it, and
    Starlette's ``TestClient`` gives every ``websocket_connect`` its own
    portal loop, so an Event here is unusable from tests. Polling on the
    holder's own loop is loop-agnostic and 50 ms of takeover latency is
    invisible.
    """

    session_id: str
    superseded: bool = False
    released: bool = False


#: How long a new consumer waits for the displaced one to stop draining
#: ``events()`` before taking over regardless. Bounded so a wedged handler
#: (half-open TCP, blocked send buffer) cannot lock the learner out.
TAKEOVER_TIMEOUT_S = 2.0

#: How often a holder checks whether it has been superseded.
SUPERSEDE_POLL_S = 0.05

_attachment: Attachment | None = None


async def acquire_consumer(
    session_id: str,
    *,
    timeout: float = TAKEOVER_TIMEOUT_S,
) -> tuple[Attachment, Attachment | None]:
    """Claim the consumer slot for ``session_id``, displacing any holder.

    Returns ``(mine, displaced)``. The claim is taken *synchronously* first so
    two concurrent callers cannot both believe they won, then the displaced
    holder is given a bounded window to stop draining the event stream — that
    wait is what guarantees output is never split between two sockets.
    """
    global _attachment
    previous = _attachment
    mine = Attachment(session_id=session_id)
    _attachment = mine
    # Remembered past the attachment's own lifetime: once a client has arrived,
    # detach is the grace timer's business and the reaper must keep its hands
    # off. Only a session that has *never* been attached is the reaper's.
    _ever_attached.add(session_id)

    if previous is None:
        return mine, None

    previous.superseded = True
    deadline = time.monotonic() + timeout
    while not previous.released and time.monotonic() < deadline:
        await asyncio.sleep(SUPERSEDE_POLL_S)
    if not previous.released:
        logger.warning(
            "previous consumer for session %s did not release within %.1fs; taking over anyway",
            previous.session_id,
            timeout,
        )
    return mine, previous


def release_consumer(attachment: Attachment) -> None:
    """Give up ``attachment``'s claim. Safe to call more than once.

    Identity-checked: a handler that has already been superseded must not clear
    the slot its successor now owns.
    """
    global _attachment
    attachment.released = True
    if _attachment is attachment:
        _attachment = None


def release_consumer_for_session(session_id: str) -> None:
    """Drop the claim on ``session_id``, whoever holds it.

    Called from the release paths so the slot's lifetime follows the *session*,
    not a socket handler's ``finally``. Without this, "refresh → End → Start"
    left the new session's first WebSocket refused by a claim belonging to a
    session that no longer exists.
    """
    global _attachment
    if _attachment is not None and _attachment.session_id == session_id:
        _attachment.superseded = True
        _attachment = None


def attached_session_id() -> str | None:
    """The session id with a live WebSocket consumer, or None."""
    return _attachment.session_id if _attachment is not None else None


def has_attached_before(session_id: str) -> bool:
    """Whether any consumer has EVER attached to ``session_id``.

    The honest test for "this socket is resuming rather than starting". A pending
    release is not that test: a page reload opens the new socket while the old
    one's ``finally`` may not have run yet, so there is often nothing to cancel
    even though the learner is plainly returning to a live session.

    Read this BEFORE ``acquire_consumer``, which is what adds the id.
    """
    return session_id in _ever_attached


def is_attached(session_id: str) -> bool:
    """True when ``session_id`` currently has a WebSocket consumer."""
    return _attachment is not None and _attachment.session_id == session_id


# --- Deferred release -------------------------------------------------------


def pending_release_ids() -> frozenset[str]:
    """Session ids with a grace timer running (i.e. detached but alive)."""
    return frozenset(_pending)


def has_pending_release(session_id: str) -> bool:
    """True when ``session_id`` is inside its grace window."""
    return session_id in _pending


def cancel_pending_release(session_id: str) -> bool:
    """Cancel the grace timer for ``session_id``.

    Returns True when a timer was actually cancelled — the caller can treat
    that as "this connection is a reattach, not a fresh start".
    """
    task = _pending.pop(session_id, None)
    if task is None:
        return False
    if not task.done():
        task.cancel()
    return True


def schedule_release(session_id: str, *, grace: float | None = None) -> None:
    """Release ``session_id`` after the grace window unless a client returns.

    Replaces any timer already running for the same id, so repeated
    detach/attach cycles cannot accumulate tasks.
    """
    cancel_pending_release(session_id)
    window = _grace_from_env() if grace is None else grace
    _pending[session_id] = asyncio.create_task(
        _deferred_release(session_id, window),
        name=f"ws-grace-release-{session_id}",
    )
    logger.info(
        "session %s detached — holding for %.0fs before release",
        session_id,
        window,
    )


async def release_now(session_id: str, *, reason: str) -> None:
    """Cancel any grace timer and release ``session_id`` immediately.

    Used when the agent has exited, the learner pressed Stop, or
    ``POST /api/session/end`` arrived during the grace window. Leaves no
    orphan timer behind.
    """
    cancel_pending_release(session_id)
    await _release_if_current(session_id, reason=reason)


# --- Slot reaper -------------------------------------------------------------
#
# ``schedule_release`` is called from exactly one place — the WS route's
# ``finally`` — so it only ever runs for a session that *had* a client. Three
# ways a slot can be pinned with no timer and no liveness poll of any kind:
#
#   * the WebSocket never attached at all (origin check refused it, a proxy
#     stripped the upgrade, a JS error before mount), so no ``finally`` ever
#     ran and nothing polls ``is_running()``;
#   * the learner ran ``studyloop session end`` in a terminal, which marks the
#     IPC file ``mode=ended`` from another process and cannot reach ``_active``;
#   * the learner ran ``studyloop clean``, which deletes the state file
#     outright — same problem.
#
# In all three the slot survives the session forever and every ``POST
# /session/start`` 409s until the server restarts. The reaper is the backstop.
#
# Locking discipline
# ------------------
# The reaper takes no locks. It reads the slot through ``active.current()``,
# documented as a lock-free pointer read, and mutates it only through
# ``release_now`` → ``_release_if_current`` → ``active.release()``, the single
# path that takes ``active._lock``. ``_release_if_current`` re-checks the
# session id, so a session that started between the reaper's observation and
# its decision can never be torn down by mistake — the same property that
# makes the grace timer safe to race. Because the reaper holds nothing while
# awaiting, it cannot deadlock against ``acquire()``. One task at a time,
# guarded by ``_reaper``, so two reapers cannot race each other either.


def reaper_running() -> bool:
    """True while the background reaper task is alive."""
    return _reaper is not None and not _reaper.done()


def start_reaper(*, interval: float | None = None) -> None:
    """Start the background reaper. Idempotent — a second call is a no-op."""
    global _reaper
    if reaper_running():
        return
    _reaper = asyncio.create_task(
        _reaper_loop(_reap_interval_from_env() if interval is None else interval),
        name="session-slot-reaper",
    )


async def stop_reaper() -> None:
    """Cancel the background reaper and wait for it to unwind."""
    global _reaper
    task, _reaper = _reaper, None
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def reap_once(
    *,
    unattached_grace: float | None = None,
    min_age: float | None = None,
) -> str | None:
    """Free the slot if nothing else can. Returns the release reason, or None.

    Split out from the loop so the decision table can be tested without
    waiting on wall-clock intervals. The order of the checks is the design:
    a dead agent outranks everything, a live grace timer outranks the rest,
    and both age-gated checks come last.
    """
    from studyloop.session import active as session_active

    current = await session_active.current()
    if current is None:
        _first_seen.clear()
        _ever_attached.clear()
        return None

    session_id = current.study_session_id
    now = time.monotonic()
    age = now - _first_seen.setdefault(session_id, now)
    for stale in [sid for sid in _first_seen if sid != session_id]:
        _first_seen.pop(stale, None)

    # 1. The agent is gone. Needs no age guard: ``is_running()`` only goes
    #    False once the child has actually been reaped.
    if not _transport_alive(current.transport):
        await release_now(session_id, reason="agent_exited")
        return "agent_exited"

    # 2. Inside the detach window the grace timer owns this session's clock.
    #    Two clocks would race over which reason gets recorded.
    pending = _pending.get(session_id)
    if pending is not None and not pending.done():
        return None

    floor = RECONCILE_MIN_AGE_SECONDS if min_age is None else min_age
    window = _unattached_grace_from_env() if unattached_grace is None else unattached_grace

    # 3. The session was ended (or cleaned) from another process.
    if age >= floor:
        reason = _ipc_disagreement(session_id)
        if reason is not None:
            await release_now(session_id, reason=reason)
            return reason

    # 4. No client ever arrived. Nothing will ever schedule a grace timer for
    #    this session, so without this it holds the slot until the server dies.
    if age >= window and session_id not in _ever_attached and not is_attached(session_id):
        await release_now(session_id, reason="never_attached")
        return "never_attached"

    return None


def _ipc_disagreement(session_id: str) -> str | None:
    """Why the IPC file says ``session_id`` is over, or None if it agrees.

    Read synchronously for the same reason as :func:`_read_topic`:
    ``read_session_state`` is a lockless ``json.loads`` over a few hundred
    bytes, and an executor hop buys a yield point we do not want.
    """
    from studyloop import session_state

    try:
        state = session_state.read_session_state()
    except Exception:  # pragma: no cover — defensive
        return None
    if not state:
        return "state_file_cleared"
    if state.get("mode") == "ended":
        return "ended_out_of_process"
    if state.get("study_session_id") != session_id:
        return "state_file_replaced"
    return None


async def _reaper_loop(interval: float) -> None:
    """Tick forever. One failing tick must never end the loop.

    A dead reaper is indistinguishable from no reaper, and the slot it was
    protecting would be pinned for the rest of the server's life.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            await reap_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover — defensive
            logger.exception("session slot reaper tick failed")


def _reap_interval_from_env() -> float:
    """Reaper tick interval, overridable for tests. Mirrors _grace_from_env."""
    raw = os.environ.get(_REAP_ENV, "").strip()
    if not raw:
        return REAP_INTERVAL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("ignoring invalid %s=%r", _REAP_ENV, raw)
        return REAP_INTERVAL_SECONDS
    if value <= 0:
        logger.warning("ignoring non-positive %s=%r", _REAP_ENV, raw)
        return REAP_INTERVAL_SECONDS
    return value


async def shutdown() -> None:
    """Cancel every grace timer and release whatever is still active.

    Wired into the app lifespan so a server stop cannot leave an orphaned
    agent child owned by a timer that will never fire.
    """
    global _attachment
    await stop_reaper()
    for session_id in list(_pending):
        cancel_pending_release(session_id)
    if _attachment is not None:
        _attachment.superseded = True
        _attachment = None

    from studyloop.session import active as session_active

    current = await session_active.current()
    if current is None:
        return
    logger.info(
        "server shutting down with session %s active — releasing",
        current.study_session_id,
    )
    await _release_if_current(current.study_session_id, reason="server_shutdown")


# --- Release audit ----------------------------------------------------------


def last_release() -> dict[str, Any] | None:
    """Why the most recent session ended, or None if none has.

    Surfaced by ``/api/session/state`` when nothing is active so the UI can
    explain a session that disappeared on grace expiry instead of leaving the
    learner to guess.
    """
    return dict(_last_release) if _last_release is not None else None


def clear_last_release() -> None:
    """Forget the previous release. Called when a new session starts."""
    global _last_release
    _last_release = None


def reset_for_tests() -> None:
    """Drop all module state. Test-only; production has one long-lived loop.

    Cancellation is best-effort: a test's grace task may belong to a
    ``TestClient`` portal loop that has already closed, and ``Task.cancel()``
    schedules work on that loop. Clearing the registries is the part that
    matters — a leaked attach entry would reject every later test's WS, and a
    leaked ``_ever_attached`` entry would make the reaper spare a session it
    should collect.
    """
    global _attachment, _last_release, _reaper
    for task in _pending.values():
        if not task.done():
            with contextlib.suppress(Exception):
                task.cancel()
    _pending.clear()
    if _reaper is not None and not _reaper.done():
        with contextlib.suppress(Exception):
            _reaper.cancel()
    _reaper = None
    _first_seen.clear()
    _ever_attached.clear()
    _attachment = None
    _last_release = None


# --- Internals --------------------------------------------------------------


def _record_release(session_id: str, reason: str, topic: str | None, agent: str | None) -> None:
    global _last_release
    _last_release = {
        "study_session_id": session_id,
        "reason": reason,
        "topic": topic,
        "agent": agent,
        "at": time.time(),
    }


def _read_topic(session_id: str) -> str | None:
    """Best-effort topic lookup for the audit record.

    Reads the IPC state *before* ``release()`` wipes it.

    Synchronous on purpose, despite the rest of this module's care about
    blocking the loop: ``read_session_state`` is a lockless
    ``json.loads(path.read_text())`` on a file of a few hundred bytes, whereas
    an ``run_in_executor`` hop adds a yield point to the WS route's ``finally``
    — and a yield point there loses a real race. Starlette's
    ``WebSocketTestSession`` cancels the ASGI task immediately after queueing
    the disconnect, so every extra await in teardown is a chance for the route
    to be cancelled mid-release. One microsecond of blocking beats that.
    """
    from studyloop import session_state

    try:
        state = session_state.read_session_state()
    except Exception:  # pragma: no cover — defensive
        return None
    if state.get("study_session_id") != session_id:
        return None
    topic = state.get("topic")
    return topic if isinstance(topic, str) else None


def _transport_alive(transport: AgentSessionTransport) -> bool:
    """Best-effort liveness. Transports without a probe are assumed alive."""
    if isinstance(transport, _LivenessProbe):
        try:
            return transport.is_running()
        except Exception:  # pragma: no cover — defensive
            logger.exception("transport.is_running() raised; assuming alive")
            return True
    return True


async def _release_if_current(session_id: str, *, reason: str) -> bool:
    """Release the active session only if it is still ``session_id``.

    The id re-check is what makes the grace timer safe to race against an
    explicit end or a fresh start: it never tears down a session it does not
    own.
    """
    from studyloop.session import active as session_active

    current = await session_active.current()
    if current is None or current.study_session_id != session_id:
        return False
    topic = _read_topic(session_id)
    _record_release(session_id, reason, topic, current.config.agent)
    # Free the consumer slot with the session it belonged to. Leaving it to the
    # WS handler's ``finally`` is what let "refresh → End → Start" refuse the
    # next session's first WebSocket with a handshake 403.
    release_consumer_for_session(session_id)
    await session_active.release()
    # Drop the reaper's bookkeeping with the session it described, so a later
    # session can never inherit "this one already had a client".
    _first_seen.pop(session_id, None)
    _ever_attached.discard(session_id)
    logger.info("session %s released (%s)", session_id, reason)
    return True


async def _deferred_release(session_id: str, grace: float) -> None:
    """Wait out the grace window, then release — unless cancelled or dead.

    Polls rather than sleeping the whole window so an agent that exits while
    detached is released at once. Without that, a dead session would hold the
    single-session slot and 409 the learner's next start for up to 90 s.
    """
    deadline = time.monotonic() + grace
    reason = "grace_expired"
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(POLL_SECONDS, remaining))

            from studyloop.session import active as session_active

            current = await session_active.current()
            if current is None or current.study_session_id != session_id:
                # Released elsewhere (explicit end, or a later start). Nothing
                # for this timer to do — and nothing to tear down.
                _pending.pop(session_id, None)
                return
            if not _transport_alive(current.transport):
                reason = "agent_exited_while_detached"
                break
    except asyncio.CancelledError:
        # A client reattached (or the server is shutting down). The caller has
        # already popped us from _pending.
        return

    try:
        await _release_if_current(session_id, reason=reason)
    except Exception:  # pragma: no cover — defensive; must not lose the pop
        logger.exception("grace release failed for session %s", session_id)
    finally:
        _pending.pop(session_id, None)
