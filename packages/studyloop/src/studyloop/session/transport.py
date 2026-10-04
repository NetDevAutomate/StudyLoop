"""AgentSessionTransport protocol — the seam between "how the agent runs"
and "how the UI observes it".

Carries raw PTY bytes plus lifecycle events for one live agent session.
Intentionally narrow so PTY- and ACP-style adapters can both satisfy it.

See private-docs/2026-05-09-refactor-agent-session-transport-plan.md
§Protocol for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class TransportEvent:
    """Marker base for the TransportEventT union.

    Exists so callers can write `isinstance(event, TransportEvent)` catch-
    alls and so mypy's match-exhaustiveness checks have a common parent.
    """


@dataclass(frozen=True)
class OutputBytes(TransportEvent):
    """Raw bytes from the agent's PTY (or synthesised by structured
    adapters that downgrade to bytes)."""

    data: bytes


@dataclass(frozen=True)
class Started(TransportEvent):
    """Emitted once after the agent child is running. The PID is NOT on
    the wire — log it server-side. `agent` is the adapter name (claude,
    codex, pi, ...), not the binary path."""

    agent: str


@dataclass(frozen=True)
class Stopped(TransportEvent):
    """Terminal lifecycle event. `returncode` is None when the child was
    killed before exit. `reason` is a short machine tag: "exit", "cancel",
    "replaced", "error"."""

    returncode: int | None
    reason: str


@dataclass(frozen=True)
class TransportError(TransportEvent):
    """Non-terminal error (e.g. queue-overflow drop, resize failure).
    Terminal failures should emit Stopped(reason="error") instead."""

    message: str


@dataclass(frozen=True)
class AgentMessage(TransportEvent):
    """Structured agent-to-host message.

    Reserved for transports that speak a richer protocol than raw bytes
    (ACP, future Anthropic SDK events). PTYTransport NEVER emits this.
    ACPTransport emits it freely for tool calls / thinking chunks / turn
    boundaries. Web UI consumers can ignore AgentMessage safely.
    """

    kind: str
    payload: dict[str, Any]


# Tagged union for match/case exhaustiveness (PEP 604).
TransportEventT = OutputBytes | Started | Stopped | TransportError | AgentMessage


@dataclass(frozen=True)
class SessionConfig:
    """Collapses start() arguments into one value.

    - study_session_id: caller-assigned session id. Propagated into the
      session_state.json file by ``session/active.py`` so dashboards/TUI
      consumers can correlate a live transport to the learner's session.
      Transports themselves do not read it.
    - agent: adapter name from the registry (not the binary path).
    - persona_file: absolute path to the canonical persona file written
      by `adapter.setup()`. The transport does NOT re-resolve this.
    - cwd: working directory for the child process.
    - env: full environment dict for execvpe. Caller is responsible for
      the child-env allowlist (see plan §Blocker B3).
    - cols, rows: initial TIOCSWINSZ dimensions. Must be sane (>= 1)
      before the child writes its first output.
    """

    study_session_id: str
    agent: str
    persona_file: str
    cwd: str
    env: dict[str, str]
    cols: int
    rows: int


class SessionAlreadyActiveError(RuntimeError):
    """Raised when a second session start is attempted while one is live.

    Callers in the route layer should map this to HTTP 409. Distinct
    from generic RuntimeError so route handlers can catch the single-
    session invariant specifically without swallowing unrelated errors.
    """


class AgentSessionTransport(Protocol):
    """Contract for launching and communicating with one agent session.

    Implementations:
        - PTYTransport (session/transports/pty.py) — pty.fork() + raw
          bytes. PTY agents (claude, codex, pi, kiro, ...).
        - StubTransport (tests/conftest.py) — pre-populated in-memory
          queue for fast unit tests.
        - ACPTransport (future, Phase 2) — JSON-RPC over stdio, emits
          AgentMessage events.

    The event stream from `events()` ends after a Stopped event. Callers
    must not call `send_input`/`resize`/`cancel`/`end` after receiving
    Stopped — behaviour is undefined.

    Implementations SHOULD also behave as async context managers so
    callers can guarantee `end()` runs via `async with transport: ...`.
    """

    async def start(self, config: SessionConfig) -> None:
        """Launch the agent child and emit Started on the events stream.

        Raises FileNotFoundError if the resolved binary is missing.
        Raises OSError on PTY fork/exec failure.
        """
        ...

    async def send_input(self, data: bytes) -> None:
        """Write learner bytes to the child's PTY stdin.

        No framing or escape handling — bytes go through verbatim.
        Ctrl-C is `b"\\x03"`; Ctrl-D is `b"\\x04"`.
        """
        ...

    async def resize(self, cols: int, rows: int) -> None:
        """Send TIOCSWINSZ to the child. May be called repeatedly."""
        ...

    def events(self) -> AsyncIterator[TransportEventT]:
        """Yield lifecycle + output events until the session ends.

        Declared as `def` returning AsyncIterator; implementations use
        `async def events(self)` with `yield` (an AsyncGenerator is a
        valid AsyncIterator).
        """
        ...

    async def cancel(self) -> None:
        """Request graceful cancellation. Sends SIGTERM; escalates to
        SIGKILL after a short grace period. Emits Stopped(reason=
        "cancel"). Idempotent."""
        ...

    async def end(self) -> None:
        """Tear down all transport resources. Closes the master fd,
        deregisters any SIGCHLD handler, reaps the child. Idempotent.
        SHOULD be called exactly once per session — typically from the
        manager's `release()` or via `__aexit__`."""
        ...

    async def __aenter__(self) -> AgentSessionTransport: ...

    async def __aexit__(self, *exc_info: object) -> None: ...


# --- Block delivery (ADR-0012; council M0 2026-10-04 Q1/Q3/Q5) --------------
#
# A ``practice_check`` envelope is not learner input: it must arrive whole, as
# one block, and the caller must learn whether it did. ``send_input`` keeps its
# fire-and-forget ``-> None`` contract for keystrokes (the Protocol above is
# unchanged); transports that can carry a block implement ``BlockDeliverer``
# beside it. The delivery module (``session/module_delivery.py``) duck-types it
# the way ``_grace._LivenessProbe`` duck-types ``is_running()`` -- a transport
# without it is reported as ``unsupported_framing``, never written to blind.

#: How the renderer frames an envelope for a transport. ``pty`` = DEC 2004
#: bracketed paste + CR (the child has enabled mode 2004); ``pty-line`` = the
#: one-printable-line fallback + CR (mode 2004 off); ``acp`` = bare labelled
#: text (a ``session/prompt`` is already one turn); ``plain`` = bare labelled
#: text for doubles and unknown adapters.
BlockFraming = Literal["pty", "pty-line", "acp", "plain"]

DeliveryWriteStatus = Literal["written", "closed", "timed_out", "unsupported_framing", "error"]


@dataclass(frozen=True)
class DeliveryWrite:
    """What became of one ``deliver_block`` call.

    - ``written``: every byte reached the child (PTY) / the prompt turn
      completed (ACP).
    - ``closed``: the write itself failed because the child is gone
      (``EIO``/``EBADF``/``EPIPE`` on the PTY master; subprocess exit on ACP).
      Observed from the write, not guessed from a pre-flight probe (M0 Q7.1).
    - ``timed_out``: ACP only -- no response to ``session/prompt`` within the
      bound; the turn was cancelled and the outcome is unknown (M0 Q5).
    - ``unsupported_framing``: the transport has no framing for a block.
    - ``error``: anything else; ``detail`` says what.
    """

    status: DeliveryWriteStatus
    detail: str = ""


@runtime_checkable
class BlockDeliverer(Protocol):
    """Optional transport capability: deliver one bounded block as data.

    Not on ``AgentSessionTransport`` -- adding it there would fail structural
    checks for doubles and adapters that do not carry blocks. ``PTYTransport``
    and ``ACPTransport`` implement it; ``module_delivery.deliver`` is its only
    caller. Ordinary learner input never goes through ``deliver_block``.
    """

    @property
    def block_framing(self) -> BlockFraming:
        """The framing the renderer must use for this transport right now."""
        ...

    async def deliver_block(self, data: bytes) -> DeliveryWrite:
        """Write *data* as one contiguous block and report what happened.

        The whole buffer or nothing observable: a transport that cannot keep
        the block contiguous against concurrent ``send_input`` calls, or
        cannot tell a closed child from a successful write, does not satisfy
        this contract.
        """
        ...
