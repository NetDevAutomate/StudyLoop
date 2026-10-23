"""What ``active.release()`` leaves on disk, for every way a web session ends.

Review 2026-10-21, remediation plan 5 (larger #1; lane 2's found-not-fixed #1, #3
and #4). ``session/active.py``'s ``release()`` ran ``clear_session_files()``
unconditionally, which deleted three files it did not own in three ways:

- the reaper's ``state_file_replaced`` release of session A deleted session B's
  freshly written state, topics and parking files;
- every web release deleted the ``mode=ended`` state the dashboard's summary view
  renders from, so a browser session never showed its summary;
- and none of the non-End releases (Stop, agent exit, grace expiry, the reaper,
  shutdown) ran the adapter teardown, so a Kiro learner's swapped agent definitions
  and the persona file stayed behind until the next session.

These tests drive the real ``_grace`` release paths, the real writers and a real
per-test ``sessions.db``; only the agent transport is a stub.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from pathlib import Path

import pytest
from _helpers import run_async
from _sessions_db_template import seed_sessions_db

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop import session_state
from studyloop.session import active
from studyloop.session.transport import SessionConfig
from studyloop.web.app import create_app
from studyloop.web.routes.session import _grace

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _stub_transport import StubTransport  # noqa: E402

_TOPIC = "Python decorators"
_PARKED = "Why does asyncio need an event loop?"


@pytest.fixture(autouse=True)
def _reset_active_state():
    run_async(active.release())
    _grace.reset_for_tests()
    yield
    run_async(active.release())
    _grace.reset_for_tests()


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return seed_sessions_db(tmp_path / "sessions.db", monkeypatch)


class _LiveTransport(StubTransport):
    """Stub with the duck-typed liveness probe the reaper and grace timer poll."""

    def __init__(self) -> None:
        super().__init__()
        self.alive = True

    def is_running(self) -> bool:
        return self.alive


def _start_live_session(
    tmp_path: Path, transport: StubTransport, *, agent: str = "claude"
) -> tuple[str, Path]:
    """A live web session as ``_start.py`` leaves it: DB row, slot, state file.

    Returns the study id and the persona file the state names.
    """
    from studyloop.history import start_study_session

    study_id = start_study_session(_TOPIC, "medium")
    assert study_id, "the seeded sessions.db refused to start a study session"
    persona_file = tmp_path / "persona.md"
    persona_file.write_text("# persona\n")
    session_dir = tmp_path / "session-dir"
    session_dir.mkdir()
    config = SessionConfig(
        study_session_id=study_id,
        agent=agent,
        persona_file=str(persona_file),
        cwd=str(session_dir),
        env={},
        cols=80,
        rows=24,
    )
    run_async(active.acquire(config, lambda: transport))
    session_state.write_session_state(
        {
            "study_session_id": study_id,
            "agent": agent,
            "topic": _TOPIC,
            "transport": "pty",
            "mode": "focus",
            "session_dir": str(session_dir),
            "persona_file": str(persona_file),
        }
    )
    return study_id, persona_file


def _record_evidence() -> None:
    session_state.append_topic("10:00", "Closures", "win", "free variables clicked")
    session_state.append_topic("10:20", "GIL", "struggling", "still fuzzy")
    session_state.append_parking(_PARKED)


# ---------------------------------------------------------------------------
# (a) the reaper's state_file_replaced release touches nothing of the newcomer's
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaper_state_file_replaced_release_leaves_the_replacing_session_files_intact(
    db: Path, tmp_path: Path
) -> None:
    """Releasing A because B now owns the state file must not alter B's files.

    B's start path wrote its claim with ``try_claim_session`` (REPLACE) and
    recorded its own topics and parking. The reaper notices the file no longer
    names A, releases A's slot -- and that release used to unlink all three of
    B's files.
    """
    transport = _LiveTransport()
    study_id_a, _ = _start_live_session(tmp_path, transport)

    b_state = {
        "study_session_id": "session-b",
        "topic": "Tries",
        "mode": "focus",
        "agent": "codex",
        "started_at": "2026-10-23T10:00:00+00:00",
    }
    session_state.STATE_FILE.write_text(json.dumps(b_state, indent=2))
    session_state.TOPICS_FILE.write_text("- [10:05] Tries | status:win | prefix trees clicked\n")
    session_state.PARKING_FILE.write_text("- How do radix trees differ?\n")
    state_before = session_state.STATE_FILE.read_bytes()
    topics_before = session_state.TOPICS_FILE.read_bytes()
    parking_before = session_state.PARKING_FILE.read_bytes()

    assert await _grace.reap_once(min_age=0.0) == "state_file_replaced"

    assert await active.current() is None, f"session {study_id_a} still holds the slot"
    assert session_state.STATE_FILE.exists(), "B's state file was deleted by A's release"
    assert session_state.STATE_FILE.read_bytes() == state_before, "B's state file was altered"
    assert session_state.TOPICS_FILE.read_bytes() == topics_before, "B's topics file was touched"
    assert session_state.PARKING_FILE.read_bytes() == parking_before, "B's parking file was touched"


# ---------------------------------------------------------------------------
# (b) a non-End web release leaves mode=ended for the dashboard summary
# ---------------------------------------------------------------------------


async def _until_released(timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while await active.current() is not None:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the session was never released")
        await asyncio.sleep(0.02)


async def _stop_or_agent_exit(sid: str, _transport: _LiveTransport) -> None:
    await _grace.release_now(sid, reason="session ended")


async def _grace_expiry(sid: str, _transport: _LiveTransport) -> None:
    _grace.schedule_release(sid, grace=0.01)
    await _until_released()


async def _reaper_sees_agent_gone(sid: str, transport: _LiveTransport) -> None:
    transport.alive = False
    assert await _grace.reap_once() == "agent_exited"


async def _server_shutdown(_sid: str, _transport: _LiveTransport) -> None:
    await _grace.shutdown()


_RELEASE_PATHS = pytest.mark.parametrize(
    "release",
    [_stop_or_agent_exit, _grace_expiry, _reaper_sees_agent_gone, _server_shutdown],
    ids=["stop-or-agent-exit", "grace-expiry", "reaper-agent-exited", "server-shutdown"],
)


@pytest.mark.asyncio
@_RELEASE_PATHS
async def test_a_web_release_leaves_a_state_file_that_reads_ended(
    release, db: Path, tmp_path: Path
) -> None:
    """The summary view renders from a ``mode=ended`` state file; keep it.

    ``persist_session_end`` writes the marker, then ``release()`` deleted the
    file, so ``/api/session/state`` answered ``{}`` and the summary branch of the
    SSE renderer was unreachable for every browser session.
    """
    transport = _LiveTransport()
    study_id, _ = _start_live_session(tmp_path, transport)
    _record_evidence()

    await release(study_id, transport)

    assert await active.current() is None
    state = session_state.read_session_state()
    assert state.get("study_session_id") == study_id, f"state file lost: {state!r}"
    assert state.get("mode") == "ended"
    # The evidence files were persisted and go; only the state stays.
    assert not session_state.TOPICS_FILE.exists()
    assert not session_state.PARKING_FILE.exists()


def test_the_dashboard_reads_the_ended_session_after_a_stop(db: Path, tmp_path: Path) -> None:
    """End to end for the learner: after a Stop, the endpoint says ``ended``."""
    transport = _LiveTransport()
    study_id, _ = _start_live_session(tmp_path, transport)
    _record_evidence()
    run_async(_grace.release_now(study_id, reason="session ended"))

    resp = TestClient(create_app()).get("/api/session/state")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("study_session_id") == study_id, body
    assert body.get("mode") == "ended", body


@pytest.mark.asyncio
async def test_a_kept_ended_state_never_blocks_the_next_start(db: Path, tmp_path: Path) -> None:
    """Keeping the file must not keep the claim: both start paths read it as free."""
    transport = _LiveTransport()
    study_id, _ = _start_live_session(tmp_path, transport)

    await _grace.release_now(study_id, reason="session ended")

    state = session_state.read_session_state()
    assert state, "the state file is gone, so nothing can render the summary"
    assert not session_state.claim_blocks_web_start(state)
    assert not session_state.claim_blocks_cli_start(state)
    assert not session_state.is_session_active()


# ---------------------------------------------------------------------------
# (c) a non-End web release runs the adapter teardown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@_RELEASE_PATHS
async def test_a_web_release_runs_the_adapter_teardown(
    release, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop, agent exit, grace expiry, the reaper and shutdown tear the adapter down.

    Only the End route ran ``teardown_session``; the other releases saved the
    session (F-WEB-02) and stopped there, so Kiro's agent-JSON restore and the
    persona-file unlink happened only when the learner pressed End.
    """
    from studyloop.agent_launcher import AGENTS

    torn_down: list[Path] = []
    adapter = AGENTS["claude"]
    monkeypatch.setitem(AGENTS, "claude", dataclasses.replace(adapter, teardown=torn_down.append))
    transport = _LiveTransport()
    study_id, persona_file = _start_live_session(tmp_path, transport)
    assert persona_file.exists()

    await release(study_id, transport)

    assert await active.current() is None, f"session {study_id} still holds the slot"
    assert torn_down == [tmp_path / "session-dir"], "the adapter teardown did not run"
    assert not persona_file.exists(), "the persona file outlived the session"
