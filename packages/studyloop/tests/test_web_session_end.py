"""Ending a web session keeps what the learner recorded during it.

Review 2026-10-21, F-WEB-01@claude-opus-5.5: ``POST /api/session/end`` released
the active slot first, and ``active.release()`` unlinks the topics and parking
files (``session_state.clear_session_files``). ``end_session_common`` then
parsed files that no longer existed, so every session ended from the browser
was saved as "No topics recorded during session." with zero wins and zero
struggles. The order these tests pin is persist first, tear down second.

The tests drive the real route, the real topic/parking writers and a real
per-test ``sessions.db`` (``seed_sessions_db``), so the assertion is on what
was actually stored rather than on which helper was called. Only the agent
transport is a stub.
"""

from __future__ import annotations

import asyncio
import sqlite3
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


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _start_live_session(
    tmp_path: Path, transport: StubTransport | None = None
) -> tuple[str, StubTransport]:
    """A live web session as ``_start.py`` leaves it: DB row, slot, state file."""
    from studyloop.history import start_study_session

    study_id = start_study_session(_TOPIC, "medium")
    assert study_id, "the seeded sessions.db refused to start a study session"
    live: StubTransport = StubTransport() if transport is None else transport
    config = SessionConfig(
        study_session_id=study_id,
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )
    run_async(active.acquire(config, lambda: live))
    session_state.write_session_state(
        {"study_session_id": study_id, "agent": "claude", "topic": _TOPIC, "transport": "pty"}
    )
    return study_id, live


def _record_evidence() -> None:
    """Two topics and one parked question, through the writers the agent uses."""
    session_state.append_topic("10:00", "Closures", "win", "free variables clicked")
    session_state.append_topic("10:20", "GIL", "struggling", "still fuzzy")
    session_state.append_parking(_PARKED)


def _stored_row(db: Path, study_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT notes, win_count, struggle_count, ended_at FROM study_sessions WHERE id = ?",
            (study_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"study_sessions row {study_id} vanished"
    return row


def test_browser_end_persists_topics_and_parking_before_release(
    client: TestClient, db: Path, tmp_path: Path
) -> None:
    study_id, transport = _start_live_session(tmp_path)
    _record_evidence()

    resp = client.post("/api/session/end")

    assert resp.status_code == 200, resp.text
    row = _stored_row(db, study_id)
    notes = row["notes"] or ""
    assert "No topics recorded during session." not in notes
    assert "Closures" in notes
    assert "GIL" in notes
    assert _PARKED in notes
    assert (row["win_count"], row["struggle_count"]) == (1, 1)
    assert row["ended_at"] is not None
    # Persisting first must not cost the release: the slot is free and the
    # agent was ended exactly once.
    assert run_async(active.current()) is None
    assert transport.end_calls == 1


def test_end_with_persistence_failure_keeps_source_files(
    client: TestClient, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed save must leave the evidence where a retry can find it.

    The browser's End dialog stays open and retries on any non-2xx response
    (session-timer.js, R-70), so the route answers with an error, keeps the
    session running and leaves the topics and parking files untouched.
    """
    from studyloop import history

    study_id, transport = _start_live_session(tmp_path)
    _record_evidence()
    topics_before = session_state.TOPICS_FILE.read_text()
    parking_before = session_state.PARKING_FILE.read_text()

    def _locked(*_args: object, **_kwargs: object) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(history, "end_study_session", _locked)

    resp = client.post("/api/session/end")

    assert resp.status_code >= 500, resp.text
    assert session_state.TOPICS_FILE.read_text() == topics_before
    assert session_state.PARKING_FILE.read_text() == parking_before
    assert session_state.read_session_state().get("study_session_id") == study_id
    # The session was not torn down behind the learner's back.
    current = run_async(active.current())
    assert current is not None and current.study_session_id == study_id
    assert transport.end_calls == 0
    assert _stored_row(db, study_id)["ended_at"] is None


class _GatedEndTransport(StubTransport):
    """A transport whose ``end()`` blocks until the test opens the gate.

    ``active.release()`` awaits ``transport.end()`` before it clears the IPC
    files, so holding it open freezes the first end request at exactly the
    point where a second request can still read the old state file.
    """

    def __init__(self) -> None:
        super().__init__()
        self.end_entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def end(self) -> None:
        self.end_entered.set()
        await self.gate.wait()
        await super().end()


def _spy(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict]:
    """Record each call to ``studyloop.history.<name>`` and run the real writer."""
    from studyloop import history

    real = getattr(history, name)
    calls: list[dict] = []

    def _recording(*args: object, **kwargs: object) -> object:
        calls.append({"args": args, **kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(history, name, _recording)
    return calls


@pytest.mark.asyncio
async def test_repeated_end_does_not_duplicate_persisted_evidence(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second End that lands while the first is still releasing changes nothing.

    The first request has persisted, marked the state ``mode=ended`` and
    deleted the topics file, but its release is still awaiting the agent. A
    second request reading the state then must not persist again: that would
    overwrite the stored summary with "No topics recorded" and store every
    progress report twice.
    """
    import httpx

    transport = _GatedEndTransport()
    study_id, _ = _start_live_session(tmp_path, transport)
    _record_evidence()
    ends = _spy(monkeypatch, "end_study_session")
    progress = _spy(monkeypatch, "record_progress")

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        first = asyncio.create_task(ac.post("/api/session/end"))
        await asyncio.wait_for(transport.end_entered.wait(), timeout=5)
        second = await asyncio.wait_for(ac.post("/api/session/end"), timeout=5)
        transport.gate.set()
        first_resp = await asyncio.wait_for(first, timeout=5)
        third = await ac.post("/api/session/end")

    assert first_resp.status_code == 200, first_resp.text
    assert second.status_code in (200, 404), second.text
    # The release keeps the ``mode=ended`` state file for the summary view (plan 5,
    # larger #1), so a later End finds an already-ended session and answers 200
    # after an idempotent teardown -- not 404, which the End dialog reads as
    # "could not end, try again" (session-timer.js, R-70) and keeps open.
    assert third.status_code == 200, third.text
    assert session_state.read_session_state().get("mode") == "ended"
    assert len(ends) == 1, f"end_study_session ran {len(ends)} times"
    assert sorted(c["topic"] for c in progress) == ["Closures", "GIL"]
    row = _stored_row(db, study_id)
    assert "Closures" in (row["notes"] or "")
    assert _PARKED in (row["notes"] or "")
    assert (row["win_count"], row["struggle_count"]) == (1, 1)
    assert transport.end_calls == 1


def test_retry_after_a_failed_end_persists_the_evidence_once(
    client: TestClient, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry the 503 invites stores each progress report exactly once.

    Pins why a failed save skips study_progress: every record_progress call
    stores a new report, so recording it on the failed attempt and again on the
    retry would double the learner's history.
    """
    from studyloop import history

    study_id, transport = _start_live_session(tmp_path)
    _record_evidence()
    progress = _spy(monkeypatch, "record_progress")
    real_end = history.end_study_session

    def _locked(*_args: object, **_kwargs: object) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(history, "end_study_session", _locked)
    assert client.post("/api/session/end").status_code == 503
    assert progress == []

    monkeypatch.setattr(history, "end_study_session", real_end)
    resp = client.post("/api/session/end")

    assert resp.status_code == 200, resp.text
    assert sorted(c["topic"] for c in progress) == ["Closures", "GIL"]
    row = _stored_row(db, study_id)
    assert (row["win_count"], row["struggle_count"]) == (1, 1)
    assert row["ended_at"] is not None
    assert transport.end_calls == 1


# ---------------------------------------------------------------------------
# F-WEB-02@claude: every other way a web session ends
# ---------------------------------------------------------------------------


class _LiveTransport(StubTransport):
    """Stub with the duck-typed liveness probe the reaper and grace timer poll."""

    def __init__(self) -> None:
        super().__init__()
        self.alive = True

    def is_running(self) -> bool:
        return self.alive


async def _until_released(timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while await active.current() is not None:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the session was never released")
        await asyncio.sleep(0.02)


async def _stop_or_agent_exit(sid: str, _transport: _LiveTransport) -> None:
    # _ws.py's finally on a Stopped event or the learner's Stop frame.
    await _grace.release_now(sid, reason="session ended")


async def _grace_expiry(sid: str, _transport: _LiveTransport) -> None:
    _grace.schedule_release(sid, grace=0.01)
    await _until_released()


async def _reaper_sees_agent_gone(sid: str, transport: _LiveTransport) -> None:
    transport.alive = False
    assert await _grace.reap_once() == "agent_exited"


async def _server_shutdown(_sid: str, _transport: _LiveTransport) -> None:
    await _grace.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "release",
    [_stop_or_agent_exit, _grace_expiry, _reaper_sees_agent_gone, _server_shutdown],
    ids=["stop-or-agent-exit", "grace-expiry", "reaper-agent-exited", "server-shutdown"],
)
async def test_web_release_paths_end_the_study_session_row(
    release, db: Path, tmp_path: Path
) -> None:
    """Stop, agent exit, grace expiry, the reaper and shutdown save the session too.

    Each of these goes through ``_grace._release_if_current`` alone, which
    released the slot (unlinking the topics and parking files) and never
    touched the database, so the study_sessions row stayed open with no notes
    and the evidence was gone for good.
    """
    transport = _LiveTransport()
    study_id, _ = _start_live_session(tmp_path, transport)
    _record_evidence()

    await release(study_id, transport)

    assert await active.current() is None
    row = _stored_row(db, study_id)
    assert row["ended_at"] is not None, "the study_sessions row was left open"
    notes = row["notes"] or ""
    assert "Closures" in notes
    assert _PARKED in notes
    assert (row["win_count"], row["struggle_count"]) == (1, 1)


def test_browser_end_persists_once_even_without_the_ended_marker(
    client: TestClient, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The End route's own release must not save the session a second time.

    The route persists, then releases through ``_grace``. Writing ``mode=ended``
    is best effort, so the release cannot rely on it to know the session was
    saved: re-persisting would read the topics file the first save deleted and
    overwrite the summary with "No topics recorded".
    """
    from studyloop.session import cleanup

    study_id, _ = _start_live_session(tmp_path)
    _record_evidence()
    ends = _spy(monkeypatch, "end_study_session")
    monkeypatch.setattr(cleanup, "_signal_dashboard_ended", lambda: None)

    resp = client.post("/api/session/end")

    assert resp.status_code == 200, resp.text
    assert len(ends) == 1, f"end_study_session ran {len(ends)} times"
    assert "Closures" in (_stored_row(db, study_id)["notes"] or "")
