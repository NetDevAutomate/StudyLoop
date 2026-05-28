"""Global pytest configuration for the studyloop test suite.

Sets environment variables BEFORE any test modules import studyloop.

The critical setup here: forcing Rich to emit plain text instead of
ANSI escape codes so CLI-output assertions (``"#42" in result.output``)
work under ``click.testing.CliRunner``, which captures stdout into a
StringIO that Rich still treats as terminal-capable.

``NO_COLOR=1`` tells Rich to drop colors. ``TERM=dumb`` is required on
top of that -- Rich keeps emitting bold/underline escape codes until
it sees a non-ANSI terminal type.

These env vars affect only the test process, never user runtime.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

# These MUST be set before any `from studyloop...` import, because
# ``studyloop.output`` (and CLI submodules) construct a module-level
# ``Console()`` whose behaviour is fixed at construction time.
#
# Hard-assign, not ``setdefault`` -- the shell typically exports
# ``TERM=xterm-256color`` which Rich treats as ANSI-capable and will
# keep emitting bold/underline escape codes even under ``NO_COLOR``.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

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
        self.permission_calls: list[tuple[str, str]] = []

    async def start(self, config: SessionConfig) -> None:
        self.start_calls.append(config)

    async def send_input(self, data: bytes) -> None:
        self.sent_input.append(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.resize_calls.append((cols, rows))

    async def events(self) -> AsyncIterator[TransportEventT]:
        for event in self._events:
            yield event

    async def send_permission(self, tool_call_id: str, option_id: str) -> None:
        self.permission_calls.append((tool_call_id, option_id))

    async def cancel(self) -> None:
        self.cancel_calls += 1

    async def end(self) -> None:
        self.end_calls += 1

    async def __aenter__(self) -> StubTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()
