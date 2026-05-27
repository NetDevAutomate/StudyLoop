"""ACPTransport — stdio JSON-RPC 2.0 transport for Agent Client Protocol CLIs.

Implements the ``AgentSessionTransport`` Protocol against Kiro and
Gemini CLIs (and any future agent that speaks the spec-canonical
method names confirmed by the Phase 1.5 capture spike in
``docs/research/2026-05-10-acp-event-shapes.md``).

Wire format:
- NDJSON over stdio (one JSON object per line).
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

from studyloop.session.transport import (
    AgentMessage,
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
    from collections.abc import AsyncGenerator, Callable

    from studyloop.session.transport import SessionConfig, TransportEventT

logger = logging.getLogger(__name__)

_INITIALIZE_TIMEOUT_S = 15.0
_SESSION_NEW_TIMEOUT_S = 60.0  # Kiro's MCP-server bootstrap takes ~13s; gemini varies. Generous margin.
_EVENT_QUEUE_MAX = 256


@dataclass
class _Running:
    proc: asyncio.subprocess.Process
    reader_task: asyncio.Task[None]
    queue: asyncio.Queue[TransportEventT | None]


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
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=config.cwd,
        )

        queue: asyncio.Queue[TransportEventT | None] = asyncio.Queue(maxsize=_EVENT_QUEUE_MAX)
        reader_task = asyncio.create_task(
            self._reader_loop(proc, queue),
            name=f"acptransport-reader-{proc.pid}",
        )
        self._state = _Running(proc=proc, reader_task=reader_task, queue=queue)

        # Handshake. If either RPC fails the state is torn down and the
        # exception propagates — caller sees a clean failure.
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
                timeout=_INITIALIZE_TIMEOUT_S,
            )
            agent_info = init_result.get("agentInfo") or {}
            self._agent_name = agent_info.get("name") or config.agent

            new_result = await asyncio.wait_for(
                self._rpc(
                    "session/new",
                    {
                        "cwd": config.cwd,
                        "mcpServers": [],
                    },
                ),
                timeout=_SESSION_NEW_TIMEOUT_S,
            )
            session_id = new_result.get("sessionId")
            if not isinstance(session_id, str):
                raise RuntimeError(f"session/new did not return a sessionId: {new_result!r}")
            self._session_id = session_id
        except Exception:
            # Tear down the subprocess so we don't leak on handshake failure.
            await self._tear_down()
            raise

        # Emit Started after successful handshake.
        await queue.put(Started(agent=self._agent_name))
        logger.info(
            "ACP session started agent=%s sessionId=%s pid=%s",
            self._agent_name,
            self._session_id,
            proc.pid,
        )

    async def send_input(self, data: bytes) -> None:
        if self._state is None or self._ended:
            return
        if self._session_id is None:
            raise RuntimeError("session not initialised — call start() first")

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._state.queue.put_nowait(
                TransportError(message=f"send_input: non-UTF-8 bytes: {exc}")
            )
            return

        # Fire-and-forget: don't block send_input on the full turn.
        # Keep a reference to the task so asyncio doesn't GC it mid-flight.
        task = asyncio.create_task(
            self._prompt_turn(text),
            name=f"acptransport-prompt-{self._next_id}",
        )
        self._prompt_tasks.add(task)
        task.add_done_callback(self._prompt_tasks.discard)

    async def _prompt_turn(self, text: str) -> None:
        """Send session/prompt and surface the terminal response as
        AgentMessage(kind='turn_end'). The turn's ``stopReason`` is
        the authoritative signal — when cancel() fires mid-turn, the
        agent reports ``cancelled`` (or equivalent) which flows
        through the payload. The reader task owns ``Stopped`` emission
        on subprocess exit."""
        state = self._state
        if state is None:
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

    async def resize(self, cols: int, rows: int) -> None:
        # ACP is turn-based; no PTY geometry to update. Declared for
        # parity with PTYTransport so the WS route can call this
        # freely.
        return

    async def events(self) -> AsyncGenerator[TransportEventT, None]:
        state = self._state
        if state is None:
            return
        while True:
            event = await state.queue.get()
            if event is None:
                return
            yield event

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
                except Exception:
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

            # Wake every pending future so awaiters don't hang.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(_RpcError("subprocess exited before responding"))
            self._pending.clear()

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
        """Route one JSON-RPC frame: response → future, notification → queue."""
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
        self._state = None

    # Accessor used only by unit tests (not part of the Protocol).
    # Hidden rather than public because callers shouldn't depend on it.
    # Kept for TDD reachability; remove if Phase 2.2+ finds no further use.


class _RpcError(RuntimeError):
    """Internal: raised when a JSON-RPC error response comes back."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
