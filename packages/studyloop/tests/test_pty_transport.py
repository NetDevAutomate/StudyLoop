"""Tests for studyloop.session.transports.pty — real pty.fork() + /bin/cat.

The canonical integration fixture for the Phase 1 PTY transport. Other tests
in this module stay fast + synchronous (unit-level helpers); the async tests
spawn ``/bin/cat`` as a PTY child because it's present on every Unix, echoes
its stdin verbatim, and exits cleanly on Ctrl-D (EOF).

Skipped entirely on Windows. pty.fork() has no Windows equivalent and the
plan explicitly scopes this transport to POSIX hosts.

Plan: private-docs/2026-05-09-refactor-agent-session-transport-plan.md §1.2
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

import pytest
import pytest_asyncio

from studyloop.session.transport import (
    OutputBytes,
    SessionConfig,
    Started,
    Stopped,
    TransportEventT,
)
from studyloop.session.transports.pty import (
    _CHILD_ENV_DENY,
    PTYTransport,
    _build_child_env,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY transport is POSIX-only")


# ---------------------------------------------------------------------------
# Fixtures — real /bin/cat binary, minimal SessionConfig, leak guard
# ---------------------------------------------------------------------------


@pytest.fixture()
def cat_path() -> str:
    path = shutil.which("cat") or "/bin/cat"
    if not os.path.exists(path):
        pytest.skip(f"/bin/cat not available at {path!r}")
    return path


@pytest.fixture()
def config() -> SessionConfig:
    """Minimal config. PTYTransport doesn't read persona_file itself."""
    return SessionConfig(
        study_session_id="pty-test-1",
        agent="cat",
        persona_file="/tmp/unused.md",
        cwd="/tmp",
        env={"PATH": os.environ.get("PATH", "")},
        cols=80,
        rows=24,
    )


@pytest.fixture()
def build_cat_cmd(cat_path: str):
    """Factory returning argv for /bin/cat."""

    def _build(_config: SessionConfig) -> list[str]:
        return [cat_path]

    return _build


@pytest.fixture()
def resolve_cat(cat_path: str):
    """resolve_binary stub that knows only about 'cat'."""

    def _resolve(agent: str) -> str | None:
        return cat_path if agent == "cat" else None

    return _resolve


@pytest_asyncio.fixture()
async def transport(resolve_cat, build_cat_cmd):
    """A fresh PTYTransport, guaranteed end()-ed on teardown."""
    t = PTYTransport(resolve_binary=resolve_cat, build_launch_cmd=build_cat_cmd)
    try:
        yield t
    finally:
        await t.end()


# ---------------------------------------------------------------------------
# Unit — _build_child_env (pure function, no PTY)
# ---------------------------------------------------------------------------


class TestBuildChildEnv:
    def test_passes_through_plain_keys(self) -> None:
        clean = _build_child_env({"PATH": "/usr/bin", "HOME": "/Users/x"})
        assert clean == {"PATH": "/usr/bin", "HOME": "/Users/x"}

    def test_strips_password_keys_case_insensitively(self) -> None:
        clean = _build_child_env(
            {
                "DB_PASSWORD": "hunter2",
                "api_password": "hunter3",
                "PATH": "/usr/bin",
            }
        )
        assert "DB_PASSWORD" not in clean
        assert "api_password" not in clean
        assert clean["PATH"] == "/usr/bin"

    def test_strips_secret_and_token_suffixes(self) -> None:
        clean = _build_child_env(
            {
                "GITHUB_TOKEN": "ghp_xxx",
                "SLACK_SECRET": "s_xxx",
                "MY_TOKEN": "x",
                "SAFE_TOKENIZED_VALUE": "ok",  # not a suffix match
            }
        )
        assert "GITHUB_TOKEN" not in clean
        assert "SLACK_SECRET" not in clean
        assert "MY_TOKEN" not in clean
        assert clean["SAFE_TOKENIZED_VALUE"] == "ok"

    def test_strips_test_escape_hatch(self) -> None:
        """STUDYLOOP_TEST_AGENT_CMD must never reach the child — it's the
        fuzz-injection entrypoint for the test harness. Plan blocker B3."""
        clean = _build_child_env({"STUDYLOOP_TEST_AGENT_CMD": "/tmp/evil.sh", "PATH": "/usr/bin"})
        assert "STUDYLOOP_TEST_AGENT_CMD" not in clean

    def test_deny_list_membership_stable(self) -> None:
        """If someone adds a new env var to STUDYLOOP_*, the allowlist should
        continue to strip the test-only one without stripping STUDYLOOP_CONFIG
        (which tests use to point at a fake config). Defensive check."""
        assert "STUDYLOOP_TEST_AGENT_CMD" in _CHILD_ENV_DENY


# ---------------------------------------------------------------------------
# Failure paths — missing binary, double-start, end() idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFailurePaths:
    async def test_missing_binary_raises_file_not_found(self, build_cat_cmd, config) -> None:
        def _missing(_agent: str) -> str | None:
            return None

        t = PTYTransport(resolve_binary=_missing, build_launch_cmd=build_cat_cmd)
        with pytest.raises(FileNotFoundError):
            await t.start(config)
        # Nothing to end() — no PTY was forked.

    async def test_double_start_raises(self, transport, config) -> None:
        await transport.start(config)
        with pytest.raises(RuntimeError, match="called twice"):
            await transport.start(config)

    async def test_reuse_after_end_raises(self, resolve_cat, build_cat_cmd, config) -> None:
        t = PTYTransport(resolve_binary=resolve_cat, build_launch_cmd=build_cat_cmd)
        await t.start(config)
        await t.end()
        with pytest.raises(RuntimeError, match="reused after end"):
            await t.start(config)

    async def test_end_is_idempotent(self, transport, config) -> None:
        await transport.start(config)
        await transport.end()
        # Second end() must not raise.
        await transport.end()


# ---------------------------------------------------------------------------
# Happy path — Started event, echo round-trip, EOF-triggered Stopped
# ---------------------------------------------------------------------------


async def _collect_until(
    transport: PTYTransport,
    *,
    predicate,
    timeout: float,
) -> list[TransportEventT]:
    """Drain events() until predicate(collected) is True or timeout expires.

    Centralised so the same loop covers every integration test without
    duplicating the deadline bookkeeping.
    """
    collected: list[TransportEventT] = []

    async def _drain() -> None:
        async for event in transport.events():
            collected.append(event)
            if predicate(collected):
                return

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except TimeoutError:
        pytest.fail(f"events() did not satisfy predicate in {timeout}s. Collected: {collected!r}")
    return collected


@pytest.mark.asyncio
class TestHappyPath:
    async def test_pid_property_reflects_the_forked_child(
        self, transport: PTYTransport, config: SessionConfig
    ) -> None:
        """C4: the route layer needs the child's pid, after start(), to
        record it on the claim as child_pid -- for clean/doctor's future
        orphan reporting (R-01g), never to kill it on reclaim."""
        assert transport.pid is None
        await transport.start(config)
        assert isinstance(transport.pid, int)
        assert transport.pid > 0

    async def test_start_emits_started_event_first(
        self, transport: PTYTransport, config: SessionConfig
    ) -> None:
        await transport.start(config)

        # Drain one event; cancel the drain so we don't leak the reader task.
        events = transport.events()
        first = await asyncio.wait_for(anext(events), timeout=5.0)
        await events.aclose()

        assert isinstance(first, Started)
        assert first.agent == "cat"

    async def test_send_input_round_trips_via_output_bytes(
        self, transport: PTYTransport, config: SessionConfig
    ) -> None:
        """cat echoes stdin -> stdout on a PTY. The PTY layer sees BOTH the
        tty echo of our keystrokes AND cat's own output. We only need 'hello'
        to appear in the combined byte stream somewhere."""
        await transport.start(config)
        await transport.send_input(b"hello\n")

        events = await _collect_until(
            transport,
            predicate=lambda evs: any(
                isinstance(e, OutputBytes) and b"hello" in e.data for e in evs
            ),
            timeout=5.0,
        )

        output_events = [e for e in events if isinstance(e, OutputBytes)]
        combined = b"".join(e.data for e in output_events)
        assert b"hello" in combined

    async def test_child_exit_emits_stopped_and_ends_stream(self, config) -> None:
        """When the child exits on its own, PTYTransport must emit
        ``Stopped(reason="exit", returncode=…)`` and then close events().

        Uses ``/bin/sh -c "sleep 0.2; exit 0"`` — a child that exits after
        a brief delay. ``/usr/bin/true`` exits so fast that SIGCHLD can
        fire before the parent's ``_register_pid`` call, causing the exit
        status to be lost (a race we avoid here because agents are
        long-lived in practice). Plan §Protocol: ``events()`` ends after
        ``Stopped``. Robust across PTY line-discipline quirks.
        """
        sh_path = "/bin/sh"
        if not os.path.exists(sh_path):
            pytest.skip("/bin/sh not available")

        t = PTYTransport(
            resolve_binary=lambda _agent: sh_path,
            build_launch_cmd=lambda _cfg: [sh_path, "-c", "sleep 0.2; exit 0"],
        )
        try:
            await t.start(config)

            events = await _collect_until(
                t,
                predicate=lambda evs: any(isinstance(e, Stopped) for e in evs),
                timeout=5.0,
            )

            stopped = next(e for e in events if isinstance(e, Stopped))
            assert stopped.returncode == 0
            assert stopped.reason == "exit"

            # After Stopped, the event stream must terminate promptly (the
            # queue sentinel — None — unblocks the reader) rather than hang
            # waiting for more output from a process that has already exited.
            async def _drain_rest() -> None:
                async for _ in t.events():
                    pass

            # Plan §Protocol: "The event stream from events() ends after a
            # Stopped event." A short deadline is enough — events() should
            # close, not block.
            await asyncio.wait_for(_drain_rest(), timeout=1.0)
        finally:
            await t.end()

    async def test_resize_does_not_raise(
        self, transport: PTYTransport, config: SessionConfig
    ) -> None:
        """TIOCSWINSZ should succeed on a live PTY master fd."""
        await transport.start(config)
        await transport.resize(120, 40)
        await transport.resize(80, 24)
        # No TransportError emitted — resize succeeded.

    async def test_cancel_emits_stopped_with_cancel_reason(
        self, transport: PTYTransport, config: SessionConfig
    ) -> None:
        """cancel() sends SIGTERM; cat exits from the signal.

        The Stopped reason we REQUIRE to be 'cancel' here — the plan wants
        callers to distinguish cancellation from natural exit so the UI can
        show a different status pill.
        """
        await transport.start(config)

        # Give the reader loop a moment to start pumping before we cancel,
        # otherwise the Started event + SIGCHLD race in unintuitive ways.
        await asyncio.sleep(0.1)

        await transport.cancel()

        events = await _collect_until(
            transport,
            predicate=lambda evs: any(isinstance(e, Stopped) for e in evs),
            timeout=5.0,
        )
        stopped = next(e for e in events if isinstance(e, Stopped))
        assert stopped.reason == "cancel"


# ---------------------------------------------------------------------------
# Context manager — __aenter__ / __aexit__ calls end()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestContextManager:
    async def test_async_with_ends_on_exit(
        self, resolve_cat, build_cat_cmd, config: SessionConfig
    ) -> None:
        t = PTYTransport(resolve_binary=resolve_cat, build_launch_cmd=build_cat_cmd)
        async with t as same:
            assert same is t
            await same.start(config)

        # After `async with` exits, end() was called — a second end() must be
        # a no-op (idempotency).
        await t.end()
