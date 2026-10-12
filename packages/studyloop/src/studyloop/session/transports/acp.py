"""ACPTransport — stdio JSON-RPC 2.0 transport for Agent Client Protocol CLIs.

Implements the ``AgentSessionTransport`` Protocol against Kiro CLI
(and any future admitted agent that speaks the spec-canonical
method names confirmed by the Phase 1.5 capture spike in
``private-docs/2026-05-10-acp-event-shapes.md``).

Wire format:
- NDJSON over stdio (one JSON object per line). Lines are unbounded by the
  protocol and large in practice; the stdout reader buffers up to
  ``_STDOUT_LINE_LIMIT`` per line and drops (never dies on) a longer one.
- Requests carry an ``id``; responses echo it. Notifications have no
  ``id`` and are dispatched through the event queue.
- Inbound ``session/update`` notifications are translated by the
  normaliser in ``acp_normaliser.py`` into ``AgentMessage`` events.

Concurrency model:
- One reader task per live session. Launched in ``start()`` after the
  subprocess spawns; it owns stdout and dispatches every frame.
- Request/response pairing via ``_pending: dict[int, Future]``. The
  reader resolves futures; ``_rpc()`` awaits them.
- Unknown-id responses and notifications without ``update`` data are
  logged and dropped (not re-raised).

Child exit detection:
- No SIGCHLD — ACP runs under uvicorn's standard asyncio loop but we
  avoid signal-based detection because PTYTransport already owns
  SIGCHLD registration in single-loop production. Instead, the reader
  hits EOF on stdout when the child exits, then we ``.wait()`` the
  subprocess and emit ``Stopped(returncode, reason)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from studyloop.session.child_env import build_child_env
from studyloop.session.transport import (
    AgentMessage,
    BlockFraming,
    DeliveryWrite,
    Started,
    Stopped,
    TransportError,
)
from studyloop.session.transports.acp_normaliser import (
    is_kiro_extension,
    normalise_session_update,
    rewrite_outbound_method,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from studyloop.session.transport import SessionConfig, TransportEventT

logger = logging.getLogger(__name__)

_INITIALIZE_TIMEOUT_S = 15.0
# Kiro's MCP-server bootstrap takes around 13 seconds. Generous margin.
_SESSION_NEW_TIMEOUT_S = 60.0
_EVENT_QUEUE_MAX = 256
# Longest NDJSON line the stdout reader will buffer before giving up on it.
#
# asyncio's StreamReader default is 64 KiB, and ``readline()`` does not return
# a long line in pieces: past the limit it raises ``ValueError`` and DISCARDS
# the buffered bytes. ACP frames have no size bound, and real ones are large:
# kiro-cli 2.29.0 answers ``session/new`` with a 45 KB result and, on a machine
# with many agents installed, precedes it with ``_kiro.dev/commands/available``
# notifications of ~74 KB each (measured 2026-10-11). Under the default limit
# the reader loop took that ``ValueError`` as end-of-stream, failed every
# pending request with "subprocess exited before responding" while the child
# was still alive, and every web Kiro ACP start was a 500. 16 MiB leaves room
# for a tool-call result that embeds a whole file; it is a cap on one line's
# buffering, not a preallocation.
_STDOUT_LINE_LIMIT = 16 * 1024 * 1024
# Bytes of child stderr kept for a handshake-failure/non-zero-exit
# diagnostic (R-07). A tail, not the whole stream -- this is a debugging
# aid, not a log sink.
_STDERR_TAIL_BYTES = 4096


class ACPHandshakeError(RuntimeError):
    """``start()`` could not complete ``initialize`` + ``session/new``.

    Raised for every handshake failure after the child was spawned -- an RPC
    error, the child exiting first, a handshake timeout, a malformed
    ``session/new`` result -- so the route has ONE exception to turn into a
    structured response instead of a bare 500. ``stderr_tail`` is whatever the
    child wrote to stderr before it failed (possibly empty): the only place
    the agent's own reason survives, since the child is torn down before the
    exception propagates. ``__cause__`` carries the underlying failure.
    """

    def __init__(self, message: str, *, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail


# --- Block delivery (ADR-0012; council M0 Q2/Q5) ------------------------------
#
# A practice_check envelope is one session/prompt like any other, but its
# caller must learn the outcome: deliver_block AWAITS the prompt's response
# (send_input for learner text stays fire-and-forget) up to this bound. On
# timeout the outcome is unknown -> `timed_out`; the turn is cancelled and the
# prompt lock is HELD until the agent has answered the cancelled prompt, so a
# later prompt cannot overlap a turn that may still be running. Never retried.
# Public (not underscored) so a test can lower it: the suite's per-test ceiling
# is 60 s.
DELIVERY_TIMEOUT_S = 120.0
# How long to wait for the cancel to be confirmed (two bounded waits: the
# session/cancel response, then the cancelled prompt's own response). If the
# agent confirms, the queue moves on exactly as after any turn. If it does NOT,
# the turn may still be running inside the agent, and releasing the queue would
# let the learner's next prompt overlap it -- so the transport is marked WEDGED
# instead (T-review finding 2; M0 Q5 "no subsequent overlap"): every later
# send_input / deliver_block fails fast with _WEDGED_MESSAGE, the one synthetic
# turn_end carries reason="wedged" so the UI can say so, and nothing overlaps.
# The way out is to end the session and start a new one.
_CANCEL_CONFIRM_TIMEOUT_S = 10.0
_WEDGED_MESSAGE = (
    "agent did not confirm cancellation of a timed-out delivery; "
    "later prompts are refused -- restart the session"
)


@dataclass
class _Running:
    proc: asyncio.subprocess.Process
    reader_task: asyncio.Task[None]
    queue: asyncio.Queue[TransportEventT | None]


class _TurnQueue:
    """FIFO serialiser for ``session/prompt`` turns (M0 Q2, Q6 invariant).

    Why not a plain ``asyncio.Lock``: ``send_input`` is fire-and-forget -- it
    creates a task and returns before that task has reached ``acquire()`` -- so a
    ``deliver_block`` call made right after it would take the lock FIRST and the
    envelope would overtake the learner's prompt. ``ticket()`` fixes a caller's
    place in line synchronously, at call time; ``async with ticket`` then waits
    for every earlier ticket to finish. Cancellation-safe: a waiter cancelled
    while queued still releases its own ticket, so the chain never stalls.
    """

    def __init__(self) -> None:
        self._tail: asyncio.Future[None] | None = None

    def ticket(self) -> _Ticket:
        loop = asyncio.get_running_loop()
        mine: asyncio.Future[None] = loop.create_future()
        ticket = _Ticket(previous=self._tail, mine=mine)
        self._tail = mine
        return ticket


class _Ticket:
    def __init__(self, *, previous: asyncio.Future[None] | None, mine: asyncio.Future[None]):
        self._previous = previous
        self._mine = mine

    async def __aenter__(self) -> _Ticket:
        if self._previous is not None:
            try:
                await self._previous
            except BaseException:
                self.release()
                raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.release()

    def release(self) -> None:
        if not self._mine.done():
            self._mine.set_result(None)


class _EventStream:
    """Cancellation-safe async iterator over the transport event queue.

    Python async generators are permanently closed when a ``CancelledError``
    propagates into their frame (PEP 525 / Python 3.10+ behaviour). Callers
    that use ``asyncio.wait_for(gen.__anext__(), timeout=N)`` trigger exactly
    this: the timeout cancels the ``__anext__`` coroutine, which injects
    ``CancelledError`` into the generator, which closes it. Subsequent calls
    raise ``StopAsyncIteration`` even though the session is still live.

    A class-based iterator avoids this entirely: ``__anext__`` is a fresh
    coroutine on every call. Cancelling one call leaves the iterator state
    (``_started_yielded``, ``_done``) intact so the next call picks up cleanly.

    Ordering guarantee: ``Started`` is synthesised as the very first item
    regardless of what is already in the queue. This eliminates the race
    where the reader pre-fills the queue with post-handshake notifications
    before ``start()`` would have enqueued ``Started`` (StreamReader.readline
    returns without yielding when stdout data is buffered, so the reader
    can drain a whole flush in one event-loop turn).
    """

    def __init__(
        self,
        queue: asyncio.Queue[TransportEventT | None],
        started_event: Started,
    ) -> None:
        self._queue = queue
        self._started_event = started_event
        self._started_yielded = False
        self._done = False

    def __aiter__(self) -> _EventStream:
        return self

    async def __anext__(self) -> TransportEventT:
        if self._done:
            raise StopAsyncIteration
        if not self._started_yielded:
            self._started_yielded = True
            return self._started_event
        event = await self._queue.get()
        if event is None:
            self._done = True
            raise StopAsyncIteration
        return event


class ACPTransport:
    """AgentSessionTransport backed by a JSON-RPC 2.0 stdio subprocess.

    One instance per session. Not reusable after ``end()``.

    Args:
        resolve_binary: ``(agent_name) -> str | None``. Returns the
            absolute path to the CLI binary, or ``None`` to fail
            start() with FileNotFoundError.
        build_argv: ``(config) -> list[str]``. Returns the argv for
            the subprocess (e.g. ``["kiro-cli", "acp"]``).
        protocol_version: ACP protocol version for the initialize
            handshake. Only ``1`` is published today.
    """

    def __init__(
        self,
        *,
        resolve_binary: Callable[[str], str | None],
        build_argv: Callable[[SessionConfig], list[str]],
        protocol_version: int = 1,
    ) -> None:
        self._resolve_binary = resolve_binary
        self._build_argv = build_argv
        self._protocol_version = protocol_version
        self._state: _Running | None = None
        self._ended = False
        self._cancel_requested = False
        self._session_id: str | None = None
        self._agent_name: str = "unknown-agent"
        self._agent_slug: str = ""
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._prompt_tasks: set[asyncio.Task[None]] = set()
        # One prompt on the wire at a time (M0 Q2): learner turns and delivered
        # blocks queue FIFO behind it, in call order, and turn_end keeps its
        # one-per-prompt meaning for the UI. cancel() deliberately does NOT queue.
        self._turns = _TurnQueue()
        # Set when a timed-out delivery's cancellation was never confirmed.
        # Checked at every entry AND after every ticket is acquired, so a prompt
        # already queued when the wedge happened is refused too, not sent.
        self._wedged = False
        self._handshake_complete = False
        # R-07: stderr was DEVNULL, so a crash before the handshake completed
        # (or a non-zero exit later) reported only a generic timeout/exit
        # code, with no reason. Drained continuously (not read once, on
        # demand) so a chatty child can never fill the pipe buffer and block
        # itself -- see _drain_stderr.
        self._stderr_tail: bytes = b""
        self._stderr_task: asyncio.Task[None] | None = None

    @property
    def pid(self) -> int | None:
        """The subprocess's pid once ``start()`` has run, else ``None``.

        Same accessor and purpose as ``PTYTransport.pid`` -- see there.
        """
        return self._state.proc.pid if self._state is not None else None

    # ---- AgentSessionTransport ------------------------------------------

    async def start(self, config: SessionConfig) -> None:
        if self._state is not None:
            raise RuntimeError("ACPTransport.start() called twice")
        if self._ended:
            raise RuntimeError("ACPTransport reused after end()")

        self._agent_slug = config.agent
        binary_path = self._resolve_binary(config.agent)
        if binary_path is None:
            raise FileNotFoundError(f"Agent binary for {config.agent!r} not found on PATH")

        argv = self._build_argv(config)
        # env= is passed explicitly. Omitting it inherits the parent environment
        # wholesale, which handed this child every credential the server holds --
        # while the sibling PTY transport stripped exactly those. See
        # studyloop.session.child_env for why the rule is shared rather than
        # duplicated.
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.cwd,
            env=build_child_env(),
            # Sizes the stdout StreamReader's readline() buffer. Without it the
            # 64 KiB default turns one long frame into a fake end-of-stream.
            limit=_STDOUT_LINE_LIMIT,
        )
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(proc),
            name=f"acptransport-stderr-{proc.pid}",
        )

        queue: asyncio.Queue[TransportEventT | None] = asyncio.Queue(maxsize=_EVENT_QUEUE_MAX)
        reader_task = asyncio.create_task(
            self._reader_loop(proc, queue),
            name=f"acptransport-reader-{proc.pid}",
        )
        self._state = _Running(proc=proc, reader_task=reader_task, queue=queue)

        # Handshake. If either RPC fails the state is torn down and ONE typed
        # exception propagates (ACPHandshakeError) naming the stage that failed
        # — caller sees a clean failure it can report, not an internal type.
        stage, bound = "initialize", _INITIALIZE_TIMEOUT_S
        try:
            init_result = await asyncio.wait_for(
                self._rpc(
                    "initialize",
                    {
                        "protocolVersion": self._protocol_version,
                        "clientCapabilities": {
                            "fs": {"readTextFile": True, "writeTextFile": True},
                            "terminal": False,
                        },
                    },
                ),
                timeout=bound,
            )
            agent_info = init_result.get("agentInfo") or {}
            self._agent_name = agent_info.get("name") or config.agent

            stage, bound = "session/new", _SESSION_NEW_TIMEOUT_S
            new_result = await asyncio.wait_for(
                self._rpc(
                    "session/new",
                    {
                        "cwd": config.cwd,
                        "mcpServers": [],
                    },
                ),
                timeout=bound,
            )
            session_id = new_result.get("sessionId")
            if not isinstance(session_id, str):
                raise RuntimeError(f"session/new did not return a sessionId: {new_result!r}")
            self._session_id = session_id
        except Exception as exc:
            # Tear down the subprocess so we don't leak on handshake failure.
            await self._tear_down()
            self._log_stderr_tail(f"ACP handshake failed for agent={config.agent!r}")
            detail = (
                f"no response within {bound:g}s"
                if isinstance(exc, TimeoutError)
                else (str(exc) or type(exc).__name__)
            )
            raise ACPHandshakeError(
                f"{stage} failed: {detail}",
                stderr_tail=self._stderr_tail.decode("utf-8", errors="replace").strip(),
            ) from exc

        # Mark handshake complete. Started is synthesised by events() as the
        # first yield — keeping it out of the queue eliminates the race between
        # the reader draining post-session/new notifications and start() putting
        # Started. The queue only ever holds post-handshake events so no
        # ordering guarantee is required of the reader.
        self._handshake_complete = True
        logger.info(
            "ACP session started agent=%s sessionId=%s pid=%s",
            self._agent_name,
            self._session_id,
            proc.pid,
        )

    @property
    def wedged(self) -> bool:
        """True once a timed-out delivery's cancel went unconfirmed (see `_WEDGED_MESSAGE`)."""
        return self._wedged

    async def send_input(self, data: bytes) -> None:
        if self._state is None or self._ended:
            return
        if self._session_id is None:
            raise RuntimeError("session not initialised — call start() first")
        if self._wedged:
            # Fail fast and loud: the agent may still be running a turn we could
            # not stop, so this prompt must not reach the wire (M0 Q5).
            _put_event(self._state.queue, TransportError(message=_WEDGED_MESSAGE))
            return

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._state.queue.put_nowait(
                TransportError(message=f"send_input: non-UTF-8 bytes: {exc}")
            )
            return

        # Fire-and-forget: don't block send_input on the full turn -- but take
        # the turn ticket NOW, so the prompt's place in line is this call's.
        # Keep a reference to the task so asyncio doesn't GC it mid-flight.
        task = asyncio.create_task(
            self._prompt_turn(text, self._turns.ticket()),
            name=f"acptransport-prompt-{self._next_id}",
        )
        self._prompt_tasks.add(task)
        task.add_done_callback(self._prompt_tasks.discard)

    async def _prompt_turn(self, text: str, ticket: _Ticket) -> None:
        """Send session/prompt and surface the terminal response as
        AgentMessage(kind='turn_end'). The turn's ``stopReason`` is
        the authoritative signal — when cancel() fires mid-turn, the
        agent reports ``cancelled`` (or equivalent) which flows
        through the payload. The reader task owns ``Stopped`` emission
        on subprocess exit."""
        state = self._state
        if state is None:
            ticket.release()
            return
        async with ticket:
            if self._wedged:
                # Queued behind the delivery that wedged us: refuse, do not send.
                _put_event(state.queue, TransportError(message=_WEDGED_MESSAGE))
                return
            try:
                result = await self._rpc(
                    "session/prompt",
                    {
                        "sessionId": self._session_id,
                        "prompt": [{"type": "text", "text": text}],
                    },
                )
            except _RpcError as exc:
                state.queue.put_nowait(TransportError(message=exc.message))
                return
            except Exception as exc:  # pragma: no cover — defensive
                state.queue.put_nowait(TransportError(message=f"prompt failed: {exc}"))
                return

            stop_reason = result.get("stopReason") or "end_turn"
            state.queue.put_nowait(AgentMessage(kind="turn_end", payload={"reason": stop_reason}))

    @property
    def block_framing(self) -> BlockFraming:
        # A session/prompt is already one turn: the bare labelled text, no bracket.
        return "acp"

    async def deliver_block(self, data: bytes, *, timeout_s: float | None = None) -> DeliveryWrite:
        """Send one block as a prompt turn and AWAIT its outcome (M0 Q5).

        Takes a turn ticket, so the block queues behind an in-flight learner turn
        -- and behind any prompt whose ``send_input`` was called before this --
        and never inside one (M0 Q2); emits the same ``turn_end`` a learner
        prompt would. ``timeout_s`` defaults to ``DELIVERY_TIMEOUT_S`` (120 s).
        On timeout: ``timed_out`` (outcome unknown), ``session/cancel`` is sent,
        and the queue is held until the agent answers the cancelled prompt. If it
        does so, later prompts proceed as normal. If it does NOT within
        ``_CANCEL_CONFIRM_TIMEOUT_S``, the transport is WEDGED: this and every
        later ``deliver_block`` reports ``closed`` and every later ``send_input``
        emits a ``TransportError`` (``_WEDGED_MESSAGE``), so no prompt can ever
        overlap the turn that may still be running (M0 Q5). Never retried.
        """
        if self._state is None or self._ended:
            return DeliveryWrite(status="closed", detail="transport not started or already ended")
        if self._wedged:
            return DeliveryWrite(status="closed", detail=_WEDGED_MESSAGE)
        if self._session_id is None:
            return DeliveryWrite(status="error", detail="session not initialised")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return DeliveryWrite(status="error", detail=f"non-UTF-8 block: {exc}")
        bound = DELIVERY_TIMEOUT_S if timeout_s is None else timeout_s

        async with self._turns.ticket():
            state = self._state
            if state is None or self._ended:
                return DeliveryWrite(status="closed", detail="transport ended before the prompt")
            if self._wedged:
                return DeliveryWrite(status="closed", detail=_WEDGED_MESSAGE)
            prompt = asyncio.ensure_future(
                self._rpc(
                    "session/prompt",
                    {
                        "sessionId": self._session_id,
                        "prompt": [{"type": "text", "text": text}],
                    },
                )
            )
            try:
                result = await asyncio.wait_for(asyncio.shield(prompt), timeout=bound)
            except TimeoutError:
                await self._cancel_and_hold(state, prompt, bound)
                return DeliveryWrite(
                    status="timed_out",
                    detail=f"no response to session/prompt within {bound:g}s; the turn was "
                    f"cancelled and the block is not retried",
                )
            except Exception as exc:
                prompt.cancel()
                if self._state is None or self._ended or state.proc.returncode is not None:
                    return DeliveryWrite(
                        status="closed", detail=f"agent exited before answering: {exc}"
                    )
                message = exc.message if isinstance(exc, _RpcError) else f"prompt failed: {exc}"
                return DeliveryWrite(status="error", detail=message)

            stop_reason = result.get("stopReason") or "end_turn"
            _put_event(state.queue, AgentMessage(kind="turn_end", payload={"reason": stop_reason}))
            return DeliveryWrite(status="written", detail=f"stopReason={stop_reason}")

    async def _cancel_and_hold(
        self,
        state: _Running,
        prompt: asyncio.Future[dict[str, Any]],
        bound: float,
    ) -> None:
        """Cancel a timed-out turn and wait, queue held, for the agent to confirm.

        ``_cancel_requested`` is deliberately NOT set: that flag is the SESSION's
        cancel and would flip the eventual ``Stopped`` reason. The agent confirms
        by answering the cancelled ``session/prompt`` (ACP: ``stopReason``
        ``cancelled``); until then a later prompt could overlap a turn that is
        still running, so the caller keeps the ticket through this call.

        Confirmed: one ``turn_end`` with the agent's stop reason; the queue moves
        on. NOT confirmed within the bound: the transport is marked wedged, a
        ``TransportError`` carries ``_WEDGED_MESSAGE``, and the one synthetic
        ``turn_end`` has ``reason="wedged"``; the caller's ticket is then released
        only so that queued prompts can be REFUSED (they check ``_wedged`` after
        acquiring), never sent.
        """
        _put_event(
            state.queue,
            TransportError(
                message=f"practice_check delivery: no response within {bound:g}s; "
                f"cancelling the turn"
            ),
        )
        try:
            await asyncio.wait_for(
                self._rpc("session/cancel", {"sessionId": self._session_id}),
                timeout=_CANCEL_CONFIRM_TIMEOUT_S,
            )
        except Exception as exc:
            logger.warning("ACP: session/cancel for a timed-out delivery got no answer: %s", exc)
        stop_reason = "cancelled"
        try:
            result = await asyncio.wait_for(prompt, timeout=_CANCEL_CONFIRM_TIMEOUT_S)
            stop_reason = result.get("stopReason") or "cancelled"
        except TimeoutError:
            # The turn may still be running inside the agent. Releasing the queue
            # would let the next learner prompt overlap it, so wedge instead.
            self._wedged = True
            stop_reason = "wedged"
            prompt.cancel()  # a late answer is dropped as an unknown id by the reader
            logger.error(
                "ACP: timed-out delivery turn not confirmed cancelled within %gs; "
                "transport wedged -- later prompts are refused",
                _CANCEL_CONFIRM_TIMEOUT_S,
            )
            _put_event(state.queue, TransportError(message=_WEDGED_MESSAGE))
        except Exception as exc:
            logger.warning("ACP: cancelled delivery turn ended with: %s", exc)
        _put_event(state.queue, AgentMessage(kind="turn_end", payload={"reason": stop_reason}))

    async def resize(self, cols: int, rows: int) -> None:
        # ACP is turn-based; no PTY geometry to update. Declared for
        # parity with PTYTransport so the WS route can call this
        # freely.
        return

    async def send_permission_response(self, request_id: int | str, outcome: dict) -> None:
        """Reply to an inbound ``session/request_permission`` JSON-RPC request.

        ACP wire protocol: the agent sends ``session/request_permission`` as a
        JSON-RPC **request** (with an ``id``).  The client (us) MUST reply via
        a JSON-RPC **response** — a frame with the matching ``id``, a
        ``result`` field, and **no** ``method`` key.

        Shape required by the ACP permission-response schema::

            {"jsonrpc": "2.0", "id": <request_id>,
             "result": {"outcome": {"outcome": "selected", "optionId": "..."}}}

        or for cancel::

            {"result": {"outcome": {"outcome": "cancelled"}}}

        This method is **not** added to the ``AgentSessionTransport`` Protocol
        — PTYTransport has no concept of permissions.  The route uses
        ``hasattr`` to call this only on transport instances that implement it.

        No-ops silently when the session is not started or already ended.
        """
        if self._state is None or self._ended:
            return
        state = self._state
        if state.proc.stdin is None or state.proc.stdin.is_closing():
            return
        frame = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"outcome": outcome},
        }
        line = (json.dumps(frame) + "\n").encode("utf-8")
        try:
            state.proc.stdin.write(line)
            await state.proc.stdin.drain()
        except Exception:
            logger.exception("send_permission_response write error")

    def events(self) -> _EventStream:
        """Return a cancellation-safe async iterator over session events.

        The first item is always ``Started`` regardless of queue state — this
        eliminates the race between the reader pre-filling the queue with
        post-handshake notifications and ``start()`` enqueuing ``Started``.

        Returns an ``_EventStream`` (class-based iterator) rather than an
        async generator so that ``asyncio.wait_for(stream.__anext__(), N)``
        timeouts do not permanently close the iterator. Each ``__anext__``
        call is a fresh coroutine; cancelling one leaves the stream alive
        for the next call. This is the failure mode that broke real-Kiro
        chat after the first attempted flake fix — Kiro's first chunk took
        longer than the route's wait_for timeout, the generator closed,
        and the UI froze on "Setting up your mentor…".
        """
        state = self._state
        if state is None or not self._handshake_complete:
            # Return a stream that immediately raises StopAsyncIteration.
            empty: asyncio.Queue[TransportEventT | None] = asyncio.Queue()
            empty.put_nowait(None)
            stream = _EventStream(empty, Started(agent=self._agent_name))
            stream._started_yielded = True  # skip the Started yield too
            return stream
        return _EventStream(state.queue, Started(agent=self._agent_name))

    async def cancel(self) -> None:
        state = self._state
        if state is None or self._ended:
            return
        self._cancel_requested = True
        if self._session_id is None:
            return
        try:
            await self._rpc("session/cancel", {"sessionId": self._session_id})
        except _RpcError:
            pass  # agent may already be gone
        except Exception:
            logger.exception("ACP session/cancel raised")

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        await self._tear_down()

    # ---- Context manager ------------------------------------------------

    async def __aenter__(self) -> ACPTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()

    # ---- Internal -------------------------------------------------------

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Continuously drain the child's stderr into a bounded tail.

        Piped stderr that nobody reads fills the OS pipe buffer and blocks
        the child -- this runs for the transport's whole life so a chatty
        agent can never deadlock on it. Only the last ``_STDERR_TAIL_BYTES``
        are kept, for the diagnostic ``_log_stderr_tail`` logs on handshake
        failure or a non-zero exit (R-07 -- previously ``DEVNULL``, so a
        crash reported only a generic timeout or exit code, with no reason).
        """
        if proc.stderr is None:
            return
        try:
            while True:
                chunk = await proc.stderr.read(1024)
                if not chunk:
                    break
                self._stderr_tail = (self._stderr_tail + chunk)[-_STDERR_TAIL_BYTES:]
        except Exception:  # pragma: no cover - defensive, pipe already closing
            pass

    def _log_stderr_tail(self, context: str) -> None:
        """Log the drained stderr tail at WARNING, if any was captured."""
        text = self._stderr_tail.decode("utf-8", errors="replace").strip()
        if text:
            logger.warning("%s; child stderr: %s", context, text)

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and await its matching response.

        Raises ``_RpcError`` on error responses; returns ``result`` as
        a dict on success (including ``{}`` when the agent returns
        ``null``).
        """
        state = self._state
        if state is None:
            raise RuntimeError("transport not started")
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut

        wire_method = rewrite_outbound_method(method, self._agent_slug)
        frame = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": wire_method,
            "params": params,
        }
        line = (json.dumps(frame) + "\n").encode("utf-8")
        if state.proc.stdin is None:
            raise RuntimeError("subprocess stdin closed")
        state.proc.stdin.write(line)
        await state.proc.stdin.drain()
        try:
            return await fut
        finally:
            self._pending.pop(req_id, None)

    async def _reader_loop(
        self,
        proc: asyncio.subprocess.Process,
        queue: asyncio.Queue[TransportEventT | None],
    ) -> None:
        """Pump stdout → (resolve pending future | enqueue event)."""
        stdout = proc.stdout
        if stdout is None:
            return
        try:
            while True:
                try:
                    line = await stdout.readline()
                except asyncio.CancelledError:
                    raise
                except ValueError as exc:
                    # One frame longer than _STDOUT_LINE_LIMIT. readline() has
                    # already discarded what it buffered and the rest of that
                    # line still arrives, so the next read returns its tail,
                    # fails json.loads below, and the stream is back in sync
                    # at the following newline. One frame lost; the child is
                    # alive and so are its pending requests -- never treat
                    # this as end-of-stream (that is exactly the bug the
                    # limit exists to prevent).
                    logger.warning(
                        "ACP: dropped a stdout frame longer than %d bytes (%s)",
                        _STDOUT_LINE_LIMIT,
                        exc,
                    )
                    continue
                except Exception:
                    logger.exception("ACP: stdout read failed; treating as end-of-stream")
                    break
                if not line:
                    break  # EOF → child exited
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("ACP: non-JSON line on stdout: %r", line[:80])
                    continue
                self._dispatch_frame(frame, queue)
        finally:
            # Await subprocess exit so returncode is available.
            try:
                returncode = await asyncio.wait_for(proc.wait(), timeout=3.0)
            except TimeoutError:
                returncode = None

            # A non-zero exit after a successful handshake is a crash, not a
            # clean shutdown -- log why, the same diagnostic the handshake
            # failure path already gets (R-07).
            if returncode not in (0, None) and not self._cancel_requested:
                self._log_stderr_tail(f"ACP child exited with code {returncode}")

            # Wake every pending future so awaiters don't hang. Say what is
            # known: a returncode means the child really exited; None means
            # its stdout is gone (or unreadable) while the process lingers.
            if returncode is None:
                failure = "agent stdout closed before it responded (process still running)"
            else:
                failure = f"agent exited with code {returncode} before responding"
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(_RpcError(failure))
            self._pending.clear()

            # Drain in-flight prompt tasks before posting the sentinel.
            # set_exception() above schedules any _prompt_turn coroutines to
            # run, but they haven't had an event-loop turn yet. If we enqueue
            # None immediately, events() terminates before _prompt_turn gets to
            # put its TransportError or turn_end on the queue — those events
            # are silently lost. Waiting here (with a short timeout) lets
            # _prompt_turn finish first so the queue ordering is:
            # [chunks…, turn_end|error, Stopped, None].
            if self._prompt_tasks:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        asyncio.gather(*self._prompt_tasks, return_exceptions=True),
                        timeout=2.0,
                    )

            # Reason flip: if cancel() set the flag before the child
            # exited, surface the exit as a clean cancel rather than
            # a natural "exit". ``_prompt_turn`` also handles the
            # flag → cancel path when a prompt was in flight; we
            # handle the no-prompt case here.
            reason = "cancel" if self._cancel_requested else "exit"
            try:
                await queue.put(Stopped(returncode=returncode, reason=reason))
                await queue.put(None)
            except RuntimeError:
                pass

    def _dispatch_frame(
        self,
        frame: dict,
        queue: asyncio.Queue[TransportEventT | None],
    ) -> None:
        """Route one JSON-RPC frame: response → future, notification → queue.

        Frame classification (JSON-RPC 2.0):
        - Inbound request:  has ``id`` + ``method``, no ``result``/``error``
        - Outbound response: has ``id`` + (``result`` or ``error``), no ``method``
        - Notification:     has ``method``, no ``id``

        The inbound-request branch MUST come before the response branch so that
        ``session/request_permission`` (which carries an ``id``) is not
        mis-classified as an unknown-id response and silently dropped.
        """
        # -- Inbound request from agent (e.g. session/request_permission) ----
        # id present + method present + no result/error → it's a request.
        if "id" in frame and "method" in frame and "result" not in frame and "error" not in frame:
            method = frame.get("method")
            params = frame.get("params") or {}
            req_id = frame["id"]
            if method == "session/request_permission":
                # Embed the request id so the route/UI can correlate the reply.
                payload = {**params, "_request_id": req_id}
                msg = AgentMessage(kind="request_permission", payload=payload)
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    logger.warning("ACP event queue full; dropping oldest")
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                    queue.put_nowait(msg)
            else:
                logger.debug("ACP: unhandled inbound request method=%r id=%r", method, req_id)
            return

        # -- Response to one of our outbound requests -------------------------
        if "id" in frame and ("result" in frame or "error" in frame):
            fut = self._pending.get(frame["id"])
            if fut is None:
                return  # Unknown id; drop.
            if fut.done():
                return
            if "error" in frame:
                err = frame["error"] or {}
                fut.set_exception(_RpcError(err.get("message") or "RPC error"))
            else:
                result = frame.get("result")
                if result is None:
                    result = {}
                fut.set_result(result)
            return

        method = frame.get("method")
        params = frame.get("params") or {}
        if method == "session/update":
            normalised = normalise_session_update(params)
            if normalised is not None:
                try:
                    queue.put_nowait(AgentMessage(**normalised))
                except asyncio.QueueFull:
                    logger.warning("ACP event queue full; dropping oldest")
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                    queue.put_nowait(AgentMessage(**normalised))
            return

        if isinstance(method, str) and is_kiro_extension(method):
            # Drop Kiro extensions by default — they're not learner-
            # visible progress and would just noise the stream.
            return

        # Unknown notification: log once and drop.
        if method is not None:
            logger.debug("ACP: unhandled notification method=%r", method)

    async def _tear_down(self) -> None:
        """Close stdin, stop reader, reap child. Idempotent."""
        state = self._state
        if state is None:
            return
        # Close stdin so the agent knows we're done.
        if state.proc.stdin and not state.proc.stdin.is_closing():
            with contextlib.suppress(Exception):
                state.proc.stdin.close()
        # Give reader a moment to drain.
        if not state.reader_task.done():
            try:
                await asyncio.wait_for(state.reader_task, timeout=2.0)
            except TimeoutError:
                state.reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await state.reader_task
        # Subprocess reap with SIGKILL fallback.
        if state.proc.returncode is None:
            try:
                state.proc.terminate()
                await asyncio.wait_for(state.proc.wait(), timeout=2.0)
            except TimeoutError:
                state.proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(state.proc.wait(), timeout=2.0)
            except ProcessLookupError:
                pass
        # Drain the event queue of stale events by enqueueing a sentinel.
        with contextlib.suppress(Exception):
            state.queue.put_nowait(None)
        # Let the stderr drain task finish reading up to EOF (the child is
        # dead or dying by now) so _stderr_tail is complete for whichever
        # caller logs it next.
        if self._stderr_task is not None and not self._stderr_task.done():
            try:
                await asyncio.wait_for(self._stderr_task, timeout=2.0)
            except TimeoutError:
                self._stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._stderr_task
        self._state = None

    # Accessor used only by unit tests (not part of the Protocol).
    # Hidden rather than public because callers shouldn't depend on it.
    # Kept for TDD reachability; remove if Phase 2.2+ finds no further use.


def _put_event(
    queue: asyncio.Queue[TransportEventT | None],
    event: TransportEventT,
) -> None:
    """Enqueue with the drop-oldest rule ``_dispatch_frame`` uses on a full queue."""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("ACP event queue full; dropping oldest")
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
        queue.put_nowait(event)


class _RpcError(RuntimeError):
    """Internal: raised when a JSON-RPC error response comes back."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
