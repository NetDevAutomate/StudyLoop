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

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

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


def _start_live_session(tmp_path: Path) -> tuple[str, StubTransport]:
    """A live web session as ``_start.py`` leaves it: DB row, slot, state file."""
    from studyloop.history import start_study_session

    study_id = start_study_session(_TOPIC, "medium")
    assert study_id, "the seeded sessions.db refused to start a study session"
    transport = StubTransport()
    config = SessionConfig(
        study_session_id=study_id,
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )
    run_async(active.acquire(config, lambda: transport))
    session_state.write_session_state(
        {"study_session_id": study_id, "agent": "claude", "topic": _TOPIC, "transport": "pty"}
    )
    return study_id, transport


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
