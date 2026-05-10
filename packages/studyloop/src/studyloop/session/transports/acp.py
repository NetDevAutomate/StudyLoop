"""ACPTransport skeleton (Phase 2 — signatures only, not implemented).

Stdio JSON-RPC 2.0 transport for Agent Client Protocol CLIs: Kiro,
Gemini, and future agents that speak the same wire format.

This file is the **spike deliverable from Phase 1.5** (see
``docs/research/2026-05-10-acp-event-shapes.md``). It declares the
method signatures required by the ``AgentSessionTransport`` Protocol
and documents the exact wire-level behaviour each method will perform
once Phase 2 implements them. The class is importable and satisfies
static-type checks against the Protocol, but every method currently
raises ``NotImplementedError``.

Confirmed in the spike: the existing Protocol accepts ACPTransport
verbatim. The ``AgentMessage`` variant in ``TransportEventT`` carries
ACP's structured notifications with no Protocol changes needed.

Phase 2 scope (see §9 of the spike doc):
- PR-A: implement this class end-to-end with unit tests using a
  scripted StubACPAgent subprocess.
- PR-B: wire ``transport="acp"`` through the REST start + WS route.
- PR-C: per-ACP-agent Playwright matrix (Kiro + Gemini).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from studyloop.session.transport import SessionConfig, TransportEventT


class ACPTransport:
    """Agent Client Protocol transport.

    One instance per session. Not reusable after ``end()``.

    The constructor takes callable injectors so production code (web
    route) wires in the agent registry while tests wire in a stub
    subprocess.

    Args:
        resolve_binary: ``(agent_name) -> str | None``. Returns the
            absolute path to the CLI binary or ``None`` (triggers
            ``FileNotFoundError`` in ``start``).
        build_argv: ``(config) -> list[str]``. Returns the argv used
            for ``execvpe``. Typically ``["kiro-cli", "acp",
            "--trust-all-tools"]`` or ``["gemini", "--acp"]``.
        protocol_version: ACP protocol version to request in the
            ``initialize`` handshake. 1 is the only published value
            at time of writing.

    See ``session.transport.AgentSessionTransport`` for the Protocol
    contract these methods satisfy.
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
        # Phase 2 will add: _proc, _reader_task, _queue, _session_id,
        # _inflight_requests, _next_id, _ended, _cancel_requested.

    # ---- AgentSessionTransport ------------------------------------------

    async def start(self, config: SessionConfig) -> None:
        """Spawn the CLI, send ``initialize``, cache ``agentInfo``,
        send ``session/new``, cache the returned sessionId. Emit
        ``Started(agent=<agentInfo.name>)`` on the events stream.

        Raises:
            FileNotFoundError: ``resolve_binary`` returned ``None``.
            OSError: subprocess spawn failed.
            RuntimeError: initialize/session handshake failed.
        """
        raise NotImplementedError("Phase 2 — see docs/research/2026-05-10-acp-event-shapes.md §9")

    async def send_input(self, data: bytes) -> None:
        """Send a ``session/prompt`` request carrying ``data`` decoded
        as UTF-8 text. ACP prompts are arrays of typed parts; this
        wraps the bytes as ``[{"type": "text", "text": <utf8>}]``.

        No-op if no session is active. Concurrent sends are serialised
        by the outer active-session lock.
        """
        raise NotImplementedError("Phase 2")

    async def resize(self, cols: int, rows: int) -> None:
        """No-op for ACP — the protocol is turn-based, not a PTY.
        Declared on the Protocol for parity with PTYTransport; the
        WS route may call it freely and it will be ignored.
        """
        # Intentionally silent — PTY-shaped callers don't care that
        # ACP ignores geometry.
        return

    def events(self) -> AsyncIterator[TransportEventT]:
        """Async iterator of lifecycle + structured events.

        Phase 2 yields:
        - ``Started(agent=<agentInfo.name>)`` once after initialize
        - ``AgentMessage(kind, payload)`` for each ``session/update``
          (post-normaliser, chrome-dropped)
        - ``TransportError(message)`` for JSON-RPC errors
        - ``Stopped(returncode, reason)`` when the child exits
        """
        raise NotImplementedError("Phase 2")

    async def cancel(self) -> None:
        """Send ``session/cancel`` for the active session. The agent
        replies with the next ``stopReason`` which the reader maps
        to ``Stopped(reason="cancel")``. Idempotent.
        """
        raise NotImplementedError("Phase 2")

    async def end(self) -> None:
        """Tear down: close stdin, cancel reader task, reap child,
        deregister any signal handlers. Idempotent. SHOULD be called
        exactly once per session.
        """
        raise NotImplementedError("Phase 2")

    # ---- Context manager ------------------------------------------------

    async def __aenter__(self) -> ACPTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()
