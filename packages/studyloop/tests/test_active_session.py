"""Tests for studyloop.session.active — module-level singleton with asyncio.Lock.

Focuses on lock semantics (TOCTOU safety), idempotency, failure-path cleanup,
and session_state.json writes. Uses StubTransport (conftest.py) so we never
touch pty.fork() here — PTY end-to-end coverage lives in test_pty_transport.py.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.4
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from studyloop.session import active
from studyloop.session.transport import (
    SessionAlreadyActiveError,
    SessionConfig,
    Started,
    Stopped,
)

# Make ``conftest`` importable regardless of pytest's rootdir (uv run pytest
# from repo root vs. from packages/studyloop both need to work).
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402 — path surgery above


@pytest_asyncio.fixture(autouse=True)
async def _reset_active_state():
    """Every test starts with no active session.

    active.py is a module-level singleton; leaking state between tests would
    cause SessionAlreadyActiveError spuriously. release() is idempotent so
    this is safe even on a clean slate.
    """
    await active.release()
    yield
    await active.release()


@pytest.fixture()
def config(tmp_path) -> SessionConfig:
    """A minimally-valid SessionConfig bound to tmp_path."""
    return SessionConfig(
        study_session_id="test-session-1",
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    """Redirect session_state.json writes into tmp_path.

    active.acquire/release delegate to studyloop.session_state, which
    resolves paths from its module-level SESSION_DIR. Monkeypatch both
    the constant AND the derived STATE_FILE so tests don't write to
    ~/.config/studyloop.
    """
    from studyloop import session_state as ss

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")


# ---------------------------------------------------------------------------
# acquire — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAcquireHappyPath:
    async def test_returns_active_session_with_config_fields(self, config):
        transport = StubTransport()
        session = await active.acquire(config, lambda: transport)

        assert session.study_session_id == "test-session-1"
        assert session.transport is transport
        assert session.config is config

    async def test_current_returns_same_session_after_acquire(self, config):
        transport = StubTransport()
        acquired = await active.acquire(config, lambda: transport)

        got = await active.current()

        assert got is acquired

    async def test_transport_start_called_with_config(self, config):
        transport = StubTransport()
        await active.acquire(config, lambda: transport)

        assert transport.start_calls == [config]

    async def test_writes_session_state_json(self, config, tmp_path):
        transport = StubTransport()
        await active.acquire(config, lambda: transport)

        state_file = tmp_path / "session-state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["study_session_id"] == "test-session-1"
        assert state["agent"] == "claude"


# ---------------------------------------------------------------------------
# acquire — single-session invariant (TOCTOU)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAcquireSingleSessionInvariant:
    async def test_second_acquire_raises_when_one_active(self, config):
        t1 = StubTransport()
        await active.acquire(config, lambda: t1)

        second_config = SessionConfig(
            study_session_id="test-session-2",
            agent="codex",
            persona_file=config.persona_file,
            cwd=config.cwd,
            env={},
            cols=80,
            rows=24,
        )

        with pytest.raises(SessionAlreadyActiveError):
            await active.acquire(second_config, lambda: StubTransport())

    async def test_error_message_names_existing_session(self, config):
        await active.acquire(config, lambda: StubTransport())

        with pytest.raises(SessionAlreadyActiveError, match="test-session-1"):
            await active.acquire(config, lambda: StubTransport())

    async def test_concurrent_acquires_only_one_wins(self, config):
        """Two concurrent acquires — exactly one wins, the other raises.

        Proves the asyncio.Lock serialises the "check empty → install
        transport" window. Without the lock, both tasks see _active is None
        and both would install.
        """
        second_config = SessionConfig(
            study_session_id="test-session-2",
            agent="codex",
            persona_file=config.persona_file,
            cwd=config.cwd,
            env={},
            cols=80,
            rows=24,
        )

        async def try_acquire(cfg):
            try:
                return await active.acquire(cfg, lambda: StubTransport())
            except SessionAlreadyActiveError as exc:
                return exc

        results = await asyncio.gather(
            try_acquire(config),
            try_acquire(second_config),
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, SessionAlreadyActiveError)]
        assert len(successes) == 1
        assert len(failures) == 1

    async def test_failed_start_leaves_slot_empty(self, config):
        """If transport.start() raises, _active must remain None.

        Without cleanup, the failed attempt could leave a half-initialised
        ActiveSession that blocks all future acquires.
        """

        class ExplodingTransport(StubTransport):
            async def start(self, cfg):
                raise FileNotFoundError("binary not on PATH")

        with pytest.raises(FileNotFoundError):
            await active.acquire(config, lambda: ExplodingTransport())

        # Slot must be empty — a fresh acquire should now succeed.
        got = await active.current()
        assert got is None

        await active.acquire(config, lambda: StubTransport())
        assert (await active.current()) is not None


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRelease:
    async def test_ends_transport(self, config):
        transport = StubTransport()
        await active.acquire(config, lambda: transport)

        await active.release()

        assert transport.end_calls == 1

    async def test_clears_current(self, config):
        await active.acquire(config, lambda: StubTransport())
        await active.release()

        assert (await active.current()) is None

    async def test_idempotent_when_already_released(self, config):
        await active.acquire(config, lambda: StubTransport())
        await active.release()

        # Second release on an already-empty slot must not raise.
        await active.release()

    async def test_idempotent_when_never_acquired(self):
        # release() on a pristine module must not raise either.
        await active.release()

    async def test_allows_fresh_acquire_after_release(self, config):
        t1 = StubTransport()
        await active.acquire(config, lambda: t1)
        await active.release()

        t2 = StubTransport()
        fresh = await active.acquire(config, lambda: t2)
        assert fresh.transport is t2


# ---------------------------------------------------------------------------
# current — getter semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCurrent:
    async def test_none_before_any_acquire(self):
        assert (await active.current()) is None

    async def test_none_after_release(self, config):
        await active.acquire(config, lambda: StubTransport())
        await active.release()
        assert (await active.current()) is None


# ---------------------------------------------------------------------------
# StubTransport — satisfies the Protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStubTransportProtocol:
    """Contract check so the stub stays honest as the protocol evolves."""

    async def test_satisfies_agent_session_transport(self):
        from studyloop.session.transport import AgentSessionTransport

        stub: AgentSessionTransport = StubTransport()
        # Structural typing — the annotation itself is the assertion at
        # type-check time. At runtime, exercise each method to catch
        # accidental signature mismatches.
        await stub.start(
            SessionConfig(
                study_session_id="x",
                agent="claude",
                persona_file="/tmp/x",
                cwd="/tmp",
                env={},
                cols=80,
                rows=24,
            )
        )
        await stub.send_input(b"hi")
        await stub.resize(100, 30)
        await stub.cancel()
        await stub.end()

    async def test_events_yields_preloaded_items(self):
        preloaded = [Started(agent="claude"), Stopped(returncode=0, reason="exit")]
        stub = StubTransport(events=preloaded)

        collected = [event async for event in stub.events()]

        assert collected == preloaded

    async def test_records_sent_input(self):
        stub = StubTransport()
        await stub.send_input(b"hello")
        await stub.send_input(b"world")

        assert stub.sent_input == [b"hello", b"world"]
