"""``StubTransport`` — the in-memory ``AgentSessionTransport`` the web/session tests share.

A plain helper module, importable as ``from _stub_transport import StubTransport``
(``conftest.py`` puts this directory on ``sys.path`` before any test module is
imported; the same route ``_helpers`` and ``_readiness`` take).

It used to be defined in ``conftest.py`` and imported with
``from conftest import StubTransport`` from 13 test modules. Under the
workspace default ``--import-mode=importlib`` pytest registers that file as
``packages.studyloop.tests.conftest``, so the bare-name import executed it a
SECOND time as a separate module -- its own ``mkdtemp`` state/vault/tmux roots,
its own copy of every hook, a different ``_TMUX_TMPDIR_ROOT`` from the plugin's
(the pid marker in ``conftest.py`` keeps the env from moving, but the duplicate
module remained). A pytest hook file is not a public helper module; this is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from studyloop.session.transport import SessionConfig, TransportEventT


class StubTransport:
    """In-memory ``AgentSessionTransport`` for unit tests.

    Satisfies the Protocol without spawning a real PTY. Preloaded events
    are yielded from ``events()``; method calls are recorded on public
    attributes for assertions.

    Usage::

        stub = StubTransport(events=[Started(agent="claude")])
        await stub.start(config)
        async for event in stub.events(): ...
        assert stub.start_calls == [config]
    """

    def __init__(self, events: Sequence[TransportEventT] = ()) -> None:
        self._events: list[TransportEventT] = list(events)
        self.start_calls: list[SessionConfig] = []
        self.sent_input: list[bytes] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.cancel_calls: int = 0
        self.end_calls: int = 0
        # Recorded send_permission_response calls.
        # Each entry: (request_id, outcome_dict)
        self.permission_calls: list[tuple[str | int, dict]] = []

    async def start(self, config: SessionConfig) -> None:
        self.start_calls.append(config)

    async def send_input(self, data: bytes) -> None:
        self.sent_input.append(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.resize_calls.append((cols, rows))

    async def events(self) -> AsyncIterator[TransportEventT]:
        for event in self._events:
            yield event

    async def send_permission_response(self, request_id: str | int, outcome: dict) -> None:
        self.permission_calls.append((request_id, outcome))

    async def cancel(self) -> None:
        self.cancel_calls += 1

    async def end(self) -> None:
        self.end_calls += 1

    async def __aenter__(self) -> StubTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()
