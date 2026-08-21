"""PTYTransport — pty.fork()-based AgentSessionTransport.

Launches a CLI agent as a child with a controlling PTY. Streams raw
output bytes and lifecycle events on the AgentSessionTransport contract.

Design notes live in docs/plans/2026-05-09-refactor-agent-session-
transport-plan.md §PTYTransport. Key choices:

- raw `pty.fork()` (not ptyprocess/pexpect)
- non-blocking master fd + executor-wrapped select+os.read
- 64 KB read buffer (co-dependent with executor dispatch — see plan)
- drop-oldest bounded queue via loop.call_soon_threadsafe
- SIGCHLD-based child-exit detection via module-level pid dispatch
- child env allowlist strips *_PASSWORD/*_SECRET/*_TOKEN + the test
  escape hatch
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import logging
import os
import pty
import re
import select
import signal
import struct
import termios
from dataclasses import dataclass
from typing import TYPE_CHECKING

from studyloop.session.transport import (
    OutputBytes,
    SessionConfig,
    Started,
    Stopped,
    TransportError,
    TransportEventT,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

logger = logging.getLogger(__name__)

# --- Tuning knobs -----------------------------------------------------------
#
# Buffer size is co-dependent with the executor-wrapped read loop. At ~10 MB/s
# localhost throughput, 64 KB reads amortise to ~160 executor dispatches/sec;
# dropping to 1 KB would be ~10,240/sec — executor overhead alone would be
# fatal (~500 ms/sec of scheduling work). Do NOT change one without the other.
_READ_BUFFER = 65536

# Block on select() briefly rather than spin. The executor thread is idle
# between reads; this is the "how much latency added to each byte" knob.
_SELECT_TIMEOUT_S = 0.05

# Bounded producer-consumer queue. 256 x 64 KB = 16 MB peak memory.
# On overflow we drop OLDEST frames (see _put_event_threadsafe).
_QUEUE_MAX = 256

# Child env keys we never pass through. Covers the test escape hatch
# (STUDYLOOP_TEST_AGENT_CMD) + studyloop config loader env + anything
# matching a secret-ish pattern. See plan Blocker B3.
_CHILD_ENV_DENY = {"STUDYLOOP_TEST_AGENT_CMD", "STUDYLOOP_CONFIG"}
_CHILD_ENV_DENY_PAT = re.compile(r"(?i)(password|secret|token)$")

# Grace window between SIGTERM and SIGKILL on cancel().
_SIGKILL_GRACE_S = 1.5


# --- SIGCHLD dispatch -------------------------------------------------------
#
# SIGCHLD in asyncio needs a single handler for the whole process. Register
# it once lazily and dispatch to a per-pid callback. Each transport registers
# itself on start() and deregisters on end() — without deregister, the handler
# leaks and fires for unrelated subprocesses elsewhere in the app. See plan
# Blocker B6.

_pid_callbacks: dict[int, Callable[[int], None]] = {}
_registered_loop: asyncio.AbstractEventLoop | None = None


def _sigchld_reaper() -> None:
    """Signal handler: reap any exited children we know about and call
    each owning transport's callback with the exit status."""
    # Reap in a loop — a single SIGCHLD can represent multiple exits.
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return
        callback = _pid_callbacks.pop(pid, None)
        if callback is not None:
            try:
                callback(status)
            except Exception:
                logger.exception("SIGCHLD callback for pid %d raised", pid)


def _ensure_sigchld_registered() -> None:
    """Install the SIGCHLD handler on the currently-running event loop.

    The handler is installed once per event loop — safe for production
    (single long-running loop, so this is effectively a one-time install)
    and for tests (pytest-asyncio creates a fresh loop per test; without
    re-registration, exits from the second test onward are silently lost).

    The prior design tracked install state with a single bool, which went
    stale as soon as the loop was replaced. We now remember the loop we
    registered against and re-register whenever ``get_running_loop()``
    returns a different object.
    """
    global _registered_loop
    loop = asyncio.get_running_loop()
    if _registered_loop is loop:
        return
    loop.add_signal_handler(signal.SIGCHLD, _sigchld_reaper)
    _registered_loop = loop


def _register_pid(pid: int, callback: Callable[[int], None]) -> None:
    _pid_callbacks[pid] = callback


def _deregister_pid(pid: int) -> None:
    _pid_callbacks.pop(pid, None)


# --- Helpers ----------------------------------------------------------------


def _build_child_env(caller_env: dict[str, str]) -> dict[str, str]:
    """Return a clean env dict for the child, with secrets stripped."""
    clean: dict[str, str] = {}
    for k, v in caller_env.items():
        if k in _CHILD_ENV_DENY:
            continue
        if _CHILD_ENV_DENY_PAT.search(k):
            continue
        clean[k] = v
    return clean


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    """Send TIOCSWINSZ to the PTY master fd.

    Must be called BEFORE the child writes its first output — CLI agents
    query terminal size at startup to lay out TUI.
    """
    winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _blocking_select_read(fd: int) -> bytes:
    """Run inside the executor. Blocks briefly on select, then reads.

    Returns b"" on select timeout (no data ready). Raises OSError if the
    fd is closed out from under us — caller interprets as EOF.
    """
    ready, _, _ = select.select([fd], [], [], _SELECT_TIMEOUT_S)
    if not ready:
        return b""
    try:
        return os.read(fd, _READ_BUFFER)
    except OSError as exc:
        if exc.errno in (errno.EIO, errno.EBADF):
            # EIO: child closed its end of the PTY. Treat as EOF.
            return b""
        raise


# --- PTYTransport -----------------------------------------------------------


@dataclass
class _Running:
    """Live state for one PTY child. Present between start() and end()."""

    pid: int
    master_fd: int
    queue: asyncio.Queue[TransportEventT | None]
    loop: asyncio.AbstractEventLoop
    reader_task: asyncio.Task[None] | None


class PTYTransport:
    """AgentSessionTransport backed by pty.fork() + raw bytes.

    One instance per session. Not reusable after end().

    Instantiate with a factory that returns the adapter's launch
    command, given a persona file path. Injecting the factory keeps
    PTYTransport decoupled from the agent registry; callers (the web
    route or CLI) wire them together.
    """

    def __init__(
        self,
        *,
        resolve_binary: Callable[[str], str | None],
        build_launch_cmd: Callable[[SessionConfig], list[str]],
    ) -> None:
        """Construct.

        resolve_binary(agent_name) -> absolute path or None. Caller is
        responsible for using shutil.which or equivalent; PTYTransport
        calls through with no fallback. None triggers FileNotFoundError.

        build_launch_cmd(config) -> argv list for execvpe. The caller
        MUST have already called adapter.setup() and adapter.mcp_setup()
        (if present) before invoking PTYTransport.start() — the transport
        does not touch adapter-specific persona scaffolding.
        """
        self._resolve_binary = resolve_binary
        self._build_launch_cmd = build_launch_cmd
        self._state: _Running | None = None
        self._ended = False
        self._cancel_requested = False

    # ---- AgentSessionTransport ---------------------------------------------

    async def start(self, config: SessionConfig) -> None:
        if self._state is not None:
            raise RuntimeError("PTYTransport.start() called twice")
        if self._ended:
            raise RuntimeError("PTYTransport reused after end()")

        binary_path = self._resolve_binary(config.agent)
        if binary_path is None:
            raise FileNotFoundError(f"Agent binary for {config.agent!r} not found on PATH")

        argv = self._build_launch_cmd(config)
        env = _build_child_env(config.env)
        loop = asyncio.get_running_loop()
        _ensure_sigchld_registered()

        queue: asyncio.Queue[TransportEventT | None] = asyncio.Queue(maxsize=_QUEUE_MAX)

        # Fork. Child exec's the agent; parent gets the master fd.
        pid, master_fd = pty.fork()
        if pid == 0:
            # CHILD
            try:
                os.chdir(config.cwd)
                # execvpe so binary_path resolution is honoured but PATH
                # still works for anything the agent may spawn.
                os.execvpe(argv[0], argv, env)
            except Exception:
                os._exit(127)
            return  # unreachable

        # PARENT
        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        _set_winsize(master_fd, config.cols, config.rows)

        state = _Running(
            pid=pid,
            master_fd=master_fd,
            queue=queue,
            loop=loop,
            reader_task=None,
        )
        self._state = state

        def on_exit(wait_status: int) -> None:
            # Called from the SIGCHLD reaper on the event loop thread.
            returncode: int | None
            if os.WIFEXITED(wait_status):
                returncode = os.WEXITSTATUS(wait_status)
            elif os.WIFSIGNALED(wait_status):
                returncode = -os.WTERMSIG(wait_status)
            else:
                returncode = None
            # cancel() sets _cancel_requested before signalling; the child's
            # exit would otherwise be reported as a natural "exit" from the
            # UI's point of view. Flag flip lets the single Stopped event
            # carry the right reason without us needing to emit two.
            reason = "cancel" if self._cancel_requested else "exit"
            self._put_event(Stopped(returncode=returncode, reason=reason))
            self._put_event(None)  # sentinel ends events()

        _register_pid(pid, on_exit)

        # Emit Started BEFORE the reader task so consumers see it first.
        await queue.put(Started(agent=config.agent))

        state.reader_task = loop.create_task(
            self._reader_loop(state), name=f"ptytransport-reader-{pid}"
        )
        logger.info(
            "PTY started agent=%s pid=%d cols=%d rows=%d",
            config.agent,
            pid,
            config.cols,
            config.rows,
        )

    def is_running(self) -> bool:
        """Whether the agent child is still alive.

        Satisfies the duck-typed liveness probe the session-slot reaper looks
        for (``_LivenessProbe`` in ``web/routes/session/_grace.py``). Until this
        existed, NOTHING in the tree implemented it, so the reaper's
        ``isinstance`` check always failed, every transport was assumed alive
        forever, and the reaper's "the agent is gone" branch was dead code. The
        cost to a learner: an agent that dies while the dashboard tab is closed
        pins the single-session slot for the whole 90 s grace window and 409s
        every ``POST /session/start`` until it expires. Nothing else can notice,
        because a detached session has no consumer draining ``events()``.

        Deliberately uses ``os.kill(pid, 0)`` rather than ``waitpid``: this
        module reaps children in its own SIGCHLD handler (``_pid_callbacks``),
        and a ``waitpid`` here would STEAL that reap, so ``on_exit`` would never
        fire and the ``Stopped`` event would be lost. Signal 0 only probes.

        Caveat: a zombie that the SIGCHLD handler has not yet reaped still
        answers signal 0, so this can report True for a moment after death. That
        is harmless — the reaper polls, and the next tick sees the truth.
        """
        state = self._state
        if state is None or self._ended:
            return False
        try:
            os.kill(state.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:  # pragma: no cover — not ours, but alive
            return True
        return True

    async def send_input(self, data: bytes) -> None:
        state = self._state
        if state is None:
            return
        try:
            os.write(state.master_fd, data)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF, errno.EPIPE):
                # Child is gone. The SIGCHLD path will emit Stopped.
                return
            raise

    async def resize(self, cols: int, rows: int) -> None:
        state = self._state
        if state is None:
            return
        try:
            _set_winsize(state.master_fd, cols, rows)
        except OSError as exc:
            self._put_event(TransportError(message=f"resize failed: {exc}"))

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
        # Flip the flag BEFORE signalling so the SIGCHLD handler's on_exit
        # sees it and emits Stopped(reason="cancel") — not "exit". Double-
        # emitting here races the handler and trips callers that expect
        # exactly one Stopped before the event stream closes.
        self._cancel_requested = True
        try:
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        # Give the child a moment to handle SIGTERM. If it's still alive
        # after the grace window, escalate to SIGKILL. Either way the
        # SIGCHLD reaper emits the single Stopped event when it fires.
        await asyncio.sleep(_SIGKILL_GRACE_S)
        with contextlib.suppress(ProcessLookupError):
            os.kill(state.pid, signal.SIGKILL)

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        state = self._state
        if state is None:
            return

        # Deregister SIGCHLD BEFORE closing the fd so a late SIGCHLD for
        # our pid doesn't try to push onto a closed queue.
        _deregister_pid(state.pid)

        if state.reader_task is not None and not state.reader_task.done():
            state.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await state.reader_task

        with contextlib.suppress(OSError):
            os.close(state.master_fd)

        # Best-effort reap in case SIGCHLD was missed (e.g. transport used
        # without the signal handler, in tests).
        with contextlib.suppress(ChildProcessError):
            os.waitpid(state.pid, os.WNOHANG)

        # Flush sentinel in case events() is still awaiting.
        self._put_event(None)
        self._state = None

    # ---- Context manager --------------------------------------------------

    async def __aenter__(self) -> PTYTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()

    # ---- Internal ---------------------------------------------------------

    async def _reader_loop(self, state: _Running) -> None:
        """Pump PTY output into the queue until the fd closes."""
        loop = state.loop
        try:
            while True:
                data = await loop.run_in_executor(None, _blocking_select_read, state.master_fd)
                if data:
                    self._put_event(OutputBytes(data=data))
                else:
                    # select timeout OR EOF. Check if child is gone.
                    if state.pid not in _pid_callbacks:
                        # SIGCHLD already fired and deregistered us.
                        return
                    # Yield to the event loop so cancel() can land.
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("PTY reader loop crashed")
            self._put_event(TransportError(message=f"reader crashed: {exc}"))
            self._put_event(Stopped(returncode=None, reason="error"))
            self._put_event(None)

    def _put_event(self, event: TransportEventT | None) -> None:
        """Enqueue from any thread.

        Drop-oldest on overflow (asyncio.Queue has no native drop-oldest;
        see plan Blocker B4). Safe to call from executor threads because
        it marshals through call_soon_threadsafe.
        """
        state = self._state
        if state is None:
            return
        # If we are on the event loop thread, skip the hop.
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is state.loop:
            self._enqueue_drop_oldest(state.queue, event)
        else:
            state.loop.call_soon_threadsafe(self._enqueue_drop_oldest, state.queue, event)

    @staticmethod
    def _enqueue_drop_oldest(
        queue: asyncio.Queue[TransportEventT | None],
        event: TransportEventT | None,
    ) -> None:
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                logger.warning("PTY output queue full, dropped oldest frame")
        with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover
            queue.put_nowait(event)
