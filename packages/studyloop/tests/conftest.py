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
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# These MUST be set before any `from studyloop...` import, because
# ``studyloop.output`` (and CLI submodules) construct a module-level
# ``Console()`` whose behaviour is fixed at construction time.
#
# Hard-assign, not ``setdefault`` -- the shell typically exports
# ``TERM=xterm-256color`` which Rich treats as ANSI-capable and will
# keep emitting bold/underline escape codes even under ``NO_COLOR``.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

# Writable-state isolation. These MUST be set here, at import time, and via
# the environment rather than a fixture:
#
#  * ``load_settings()`` / ``get_db_path()`` read them at call time, so every
#    in-process caller is covered without monkeypatching each one.
#  * a test that shells out to the CLI inherits only the environment — a
#    monkeypatched function does not cross the process boundary. That gap is
#    how the suite previously migrated the learner's real ``sessions.db`` and
#    wrote a poisoned picker cache into their real state dir. See
#    ``docs/issues/0005-vendor-picker-lists-repo-directories.md``.
#
# Individual tests may still point these at their own tmp_path; the default
# below only guarantees that *nothing* lands in the real user directories.
_TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-state-"))
os.environ.setdefault("STUDYLOOP_STATE_DIR", str(_TEST_STATE_ROOT / "state"))
os.environ.setdefault("STUDYLOOP_DB", str(_TEST_STATE_ROOT / "sessions.db"))

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from studyloop.session.transport import SessionConfig, TransportEventT


# ---------------------------------------------------------------------------
# Test isolation: redirect state_dir to a temp directory so no test leaks
# into ~/.local/share/studyloop. The env vars set at import time above are
# the primary mechanism (they survive subprocess boundaries); this autouse
# fixture is the belt-and-braces layer for any test that builds a Settings
# object directly and bypasses the environment.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_state_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ``load_settings().state_dir`` out of the learner's real state dir.

    Prevents any test from reading or writing the user's real
    ~/.local/share/studyloop — the root cause of issue 0005.

    Uses tmp_path_factory (not tmp_path) so the isolated dir lives in a
    separate temp tree that won't pollute tests using tmp_path as their
    own working directory.
    """
    isolated_state = tmp_path_factory.mktemp("studyloop-isolated-state")

    from studyloop import settings as _settings_mod

    _original_load = _settings_mod.load_settings

    def _patched_load_settings():
        s = _original_load()
        # Only override when the test has not already chosen a state_dir
        # (detected by it still pointing at the production default).
        if s.state_dir == _settings_mod.DEFAULT_STATE_DIR:
            s.state_dir = isolated_state
        return s

    monkeypatch.setattr(_settings_mod, "load_settings", _patched_load_settings)


def test_no_test_writes_to_real_user_state() -> None:
    """Guard: the suite must never resolve writable state to the real dirs.

    Asserted as a test, not just a fixture, so the invariant fails loudly in
    CI if the env-var wiring above is ever removed or reordered.

    Both resolvers are checked. ``studyloop.settings`` and
    ``agent_session_tools.config_loader`` compute the session DB path
    independently, and covering only one of them left the real database being
    migrated by test runs.
    """
    from agent_session_tools.config_loader import DEFAULT_CONFIG
    from agent_session_tools.config_loader import get_db_path as ast_get_db_path
    from studyloop.settings import (
        DEFAULT_DB,
        DEFAULT_STATE_DIR,
        get_db_path,
        get_state_dir,
        load_settings,
    )

    assert get_state_dir() != DEFAULT_STATE_DIR, "state_dir escaped test isolation"
    assert get_db_path() != DEFAULT_DB, "studyloop session DB escaped test isolation"
    assert load_settings().session_db != DEFAULT_DB, (
        "Settings.session_db escaped test isolation (history/_connection.py reads this one)"
    )
    assert str(ast_get_db_path()) != DEFAULT_CONFIG["database"]["path"], (
        "agent_session_tools session DB escaped test isolation"
    )


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


# ---------------------------------------------------------------------------
# Multiplexer harness fixture (T4 — journey tests)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["tmux", "herdr"])
def mux_harness(request: pytest.FixtureRequest):
    """Parameterised multiplexer harness — yields one instance per backend.

    Tests using this fixture run TWICE: once for tmux, once for herdr.
    Skips gracefully if the backend binary is not available (CI without herdr).
    """
    import shutil

    from harness.multiplexer import MultiplexerHarness

    backend_name: str = request.param

    if backend_name == "tmux" and not shutil.which("tmux"):
        pytest.skip("tmux not available")
    if backend_name == "herdr" and not shutil.which("herdr"):
        pytest.skip("herdr not available")

    with MultiplexerHarness.from_backend_name(backend_name) as harness:
        yield harness


@pytest.fixture()
def tmux_mux_harness():
    """tmux-only multiplexer harness (for tmux-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("tmux"):
        pytest.skip("tmux not available")
    with MultiplexerHarness.from_backend_name("tmux") as harness:
        yield harness


@pytest.fixture()
def herdr_mux_harness():
    """herdr-only multiplexer harness (for herdr-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("herdr"):
        pytest.skip("herdr not available")
    with MultiplexerHarness.from_backend_name("herdr") as harness:
        yield harness
