"""Read-only dashboard endpoints must degrade, never 500.

`GET /api/session/last` is hit on every page load to power the Today panel's
"Resume: <topic>" shortcut. It is a convenience lookup the learner never asked
for, so any database problem — a briefly locked SQLite file while a session-end
write commits, a missing agent-session-tools install, a drifted schema — must
produce "no previous session", not a 500 that surfaces as a console error and
an error toast.

This was a real failure: the e2e browser journey caught
`HTTP 500 /api/session/last` under concurrent session writes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app


def _client() -> TestClient:
    # raise_server_exceptions=False so an unhandled handler exception is
    # reported as the 500 the browser would see, rather than re-raised here.
    return TestClient(create_app(study_dirs=[]), raise_server_exceptions=False)


def test_session_last_returns_empty_dict_when_the_db_is_locked(monkeypatch) -> None:
    """A locked/erroring DB yields {} and HTTP 200, not a 500."""
    import sqlite3

    def _boom() -> dict:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("studyloop.history.sessions.get_last_study_session", _boom)
    resp = _client().get("/api/session/last")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {}


def test_session_last_returns_empty_dict_when_sessions_db_is_unavailable(monkeypatch) -> None:
    """A missing agent-session-tools install degrades the same way."""

    def _boom() -> dict:
        raise ImportError("No module named 'agent_session_tools'")

    monkeypatch.setattr("studyloop.history.sessions.get_last_study_session", _boom)
    resp = _client().get("/api/session/last")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_session_last_passes_through_a_real_row(monkeypatch) -> None:
    """The degrade path must not swallow a successful lookup."""
    row = {"topic": "python decorators", "energy_level": "6", "started_at": "2026-01-01T09:00:00"}
    monkeypatch.setattr("studyloop.history.sessions.get_last_study_session", lambda: row)
    resp = _client().get("/api/session/last")
    assert resp.status_code == 200
    assert resp.json()["topic"] == "python decorators"


def test_session_last_returns_empty_dict_when_there_is_no_session(monkeypatch) -> None:
    """None from the history layer becomes {}, not null."""
    monkeypatch.setattr("studyloop.history.sessions.get_last_study_session", lambda: None)
    resp = _client().get("/api/session/last")
    assert resp.status_code == 200
    assert resp.json() == {}
