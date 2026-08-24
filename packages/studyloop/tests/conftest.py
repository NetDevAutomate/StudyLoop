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
import shutil
import subprocess
import tempfile
import time
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
_TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-state-")).resolve()
os.environ.setdefault("STUDYLOOP_STATE_DIR", str(_TEST_STATE_ROOT / "state"))
os.environ.setdefault("STUDYLOOP_DB", str(_TEST_STATE_ROOT / "sessions.db"))
os.environ["STUDYLOOP_SESSION_DIR"] = str(_TEST_STATE_ROOT / "session-ipc")
# Hard-assign like NO_COLOR/TERM above. A developer shell may export a plans
# path inside a git worktree; child web servers inherit it and the containment
# guard then (correctly) refuses the symlink before browser tests can start.
os.environ["STUDYLOOP_PLANS_DIR"] = str(_TEST_STATE_ROOT / "plans")

# Process-state isolation. Integration tests exercise the real tmux and Herdr
# CLIs, including production cleanup that intentionally closes every
# ``study-*`` session. Give each pytest process private backend endpoints so
# that behaviour cannot see or destroy a learner's real workspaces.
_TEST_PROCESS_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-process-", dir="/tmp")).resolve()
_TEST_TMUX_ROOT = _TEST_PROCESS_ROOT / "tmux"
_TEST_TMUX_ROOT.mkdir(mode=0o700)
_TEST_TMUX_CONFIG = _TEST_TMUX_ROOT / "tmux.conf"
_TEST_TMUX_CONFIG.write_text(
    'set-option -g exit-empty off\nset-option -g default-terminal "tmux-256color"\n',
    encoding="utf-8",
)
os.environ["TMUX_TMPDIR"] = str(_TEST_TMUX_ROOT)
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)

_TEST_XDG_CONFIG_HOME = _TEST_PROCESS_ROOT / "xdg-config"
_TEST_XDG_CONFIG_HOME.mkdir(mode=0o700)

_TEST_HERDR_ROOT = _TEST_XDG_CONFIG_HOME / "herdr"
_TEST_HERDR_ROOT.mkdir(mode=0o700)
_TEST_HERDR_CONFIG = _TEST_HERDR_ROOT / "config.toml"
_TEST_HERDR_CONFIG.write_text(
    "onboarding = false\n[update]\nversion_check = false\nmanifest_check = false\n",
    encoding="utf-8",
)
os.environ["HERDR_SOCKET_PATH"] = str(_TEST_HERDR_ROOT / "herdr.sock")
os.environ["HERDR_CONFIG_PATH"] = str(_TEST_HERDR_CONFIG)
for _herdr_context_var in (
    "HERDR_ENV",
    "HERDR_WORKSPACE_ID",
    "HERDR_TAB_ID",
    "HERDR_PANE_ID",
):
    os.environ.pop(_herdr_context_var, None)

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


@pytest.fixture(scope="session", autouse=True)
def _isolated_tmux_server():
    """Pre-start the private tmux server without loading user configuration."""
    if not shutil.which("tmux"):
        yield
        return

    tmux_env = dict(os.environ)
    tmux_env.pop("TMUX", None)
    tmux_env.pop("TMUX_PANE", None)
    tmux_env["TMUX_TMPDIR"] = str(_TEST_TMUX_ROOT)
    started = subprocess.run(
        ["tmux", "-f", str(_TEST_TMUX_CONFIG), "start-server"],
        env=tmux_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if started.returncode != 0:
        pytest.fail(f"isolated tmux test server failed to start: {started.stderr}")

    try:
        yield
    finally:
        subprocess.run(
            ["tmux", "kill-server"],
            env=tmux_env,
            capture_output=True,
            check=False,
            timeout=5,
        )


@pytest.fixture(scope="session", autouse=True)
def _isolated_herdr_server(request: pytest.FixtureRequest):
    """Run one private Herdr server when selected integration tests need it."""
    integration_selected = any(
        item.get_closest_marker("integration") is not None for item in request.session.items
    )
    if not integration_selected or not shutil.which("herdr"):
        yield
        return

    previous_xdg_config = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(_TEST_XDG_CONFIG_HOME)

    def restore_xdg_config() -> None:
        if previous_xdg_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = previous_xdg_config

    herdr_env = dict(os.environ)
    herdr_env.pop("HERDR_ENV", None)
    herdr_env["XDG_CONFIG_HOME"] = str(_TEST_XDG_CONFIG_HOME)
    herdr_env["HERDR_SOCKET_PATH"] = str(_TEST_HERDR_ROOT / "herdr.sock")
    herdr_env["HERDR_CONFIG_PATH"] = str(_TEST_HERDR_CONFIG)
    server = subprocess.Popen(
        ["herdr", "server"],
        env=herdr_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(50):
        status = subprocess.run(
            ["herdr", "status", "server"],
            env=herdr_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if status.returncode == 0 and "status: running" in status.stdout:
            break
        if server.poll() is not None:
            restore_xdg_config()
            pytest.fail("isolated Herdr test server exited before becoming ready")
        time.sleep(0.1)
    else:
        server.terminate()
        server.wait(timeout=5)
        restore_xdg_config()
        pytest.fail("isolated Herdr test server did not become ready")

    try:
        yield
    finally:
        subprocess.run(
            ["herdr", "server", "stop"],
            env=herdr_env,
            capture_output=True,
            check=False,
            timeout=10,
        )
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=5)
        restore_xdg_config()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Stop only the private multiplexer servers created by this test process."""
    del session, exitstatus

    tmux_env = dict(os.environ)
    tmux_env.pop("TMUX", None)
    tmux_env.pop("TMUX_PANE", None)
    tmux_env["TMUX_TMPDIR"] = str(_TEST_TMUX_ROOT)
    if shutil.which("tmux"):
        subprocess.run(
            ["tmux", "kill-server"],
            env=tmux_env,
            capture_output=True,
            check=False,
            timeout=5,
        )

    herdr_env = dict(os.environ)
    herdr_env.pop("HERDR_ENV", None)
    herdr_env["XDG_CONFIG_HOME"] = str(_TEST_XDG_CONFIG_HOME)
    herdr_env["HERDR_SOCKET_PATH"] = str(_TEST_HERDR_ROOT / "herdr.sock")
    herdr_env["HERDR_CONFIG_PATH"] = str(_TEST_HERDR_CONFIG)
    if shutil.which("herdr"):
        subprocess.run(
            ["herdr", "server", "stop"],
            env=herdr_env,
            capture_output=True,
            check=False,
            timeout=10,
        )
    shutil.rmtree(_TEST_PROCESS_ROOT, ignore_errors=True)


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


# ---------------------------------------------------------------------------
# e2e tests get a longer per-test timeout than the 60s unit ceiling.
#
# The pytest-timeout ceiling in pyproject.toml exists to stop one hanging test
# eating the whole run (an unbounded TestClient WebSocket receive did exactly
# that). 60s is right for unit tests -- the slowest is ~13s -- but far too tight
# for e2e, which drives a real browser against a subprocess-hosted server and
# has individual waits already allowing 60-180s. test_journey_generate_review's
# generate walk alone measures ~61s, so a flat 60s kills it before its own
# deadline and reports a timeout that looks like a product bug.
#
# Applied as a collection hook rather than a `pytest.mark.timeout` on each of
# the 20 e2e modules: one rule, no per-module drift, and it covers modules added
# later. An explicit timeout mark on a test or module still wins.
# ---------------------------------------------------------------------------

E2E_TIMEOUT_SECONDS = 300


def pytest_collection_modifyitems(items) -> None:
    """Grant every e2e-marked test E2E_TIMEOUT_SECONDS unless it sets its own."""
    for item in items:
        if item.get_closest_marker("e2e") and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(E2E_TIMEOUT_SECONDS))
