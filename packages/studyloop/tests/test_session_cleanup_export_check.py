"""The pi end-of-session export check (review 2026-10-21, item F#5 / plan-5 D).

pi exports its own transcript to the sessions database from a ``session_shutdown``
extension (``agents/pi/extensions/studyloop-session-export.ts`` runs
``session-export --pi-only``), and pi 1.1.0 awaits that handler before its process
exits -- so by the time the tmux wrapper runs ``cleanup_on_exit()`` the export has
either landed or failed. Nothing told the learner which. ``record_harness_export_check``
looks for the row and records the verdict in the session state, where the dashboard's
ended view reads it.

The check runs BEFORE ``teardown_session``: that kills the tmux session the wrapper
runs in, so nothing after it ever executes.

The sqlite fixtures here live under ``tmp_path`` (the TMPDIR contract); the rows are
shaped exactly as ``agent_session_tools/exporters/pi.py`` writes them (``source='pi'``,
``project_path`` = the JSONL ``cwd``, ``updated_at`` = the last message's ``Z`` stamp).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from _sessions_db_template import seed_sessions_db

from studyloop import session_state

if TYPE_CHECKING:
    from pathlib import Path

_STARTED_AT = "2026-10-23T10:00:00+00:00"
_AFTER = "2026-10-23T10:30:00.000Z"
_BEFORE = "2026-10-23T09:30:00.000Z"


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return seed_sessions_db(tmp_path / "sessions.db", monkeypatch)


def _insert_pi_row(db: Path, project_path: Path, updated_at: str, row_id: str = "pi-1") -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO sessions (id, source, project_path, created_at, updated_at) "
            "VALUES (?, 'pi', ?, ?, ?)",
            (row_id, str(project_path), updated_at, updated_at),
        )
        conn.commit()
    finally:
        conn.close()


def _pi_state(session_dir: Path, *, agent: str = "pi") -> dict:
    state = {
        "study_session_id": "study-1",
        "agent": agent,
        "topic": "Tries",
        "mode": "focus",
        "started_at": _STARTED_AT,
        "session_dir": str(session_dir),
    }
    session_state.write_session_state(state)
    return state


def _export_check() -> dict | None:
    return session_state.read_session_state().get("export_check")


def test_a_row_updated_after_the_start_is_an_ok_export(db: Path, tmp_path: Path) -> None:
    from studyloop.session.cleanup import record_harness_export_check

    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    _insert_pi_row(db, session_dir, _AFTER)
    state = _pi_state(session_dir)

    record_harness_export_check(state)

    check = _export_check()
    assert check is not None, "no export_check was recorded"
    assert check["harness"] == "pi"
    assert check["status"] == "ok"
    datetime.fromisoformat(check["checked_at"])  # a real timestamp, not a placeholder


def test_no_database_file_is_a_missing_export_without_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from studyloop.session.cleanup import record_harness_export_check

    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "never-created.db"))
    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    state = _pi_state(session_dir)

    record_harness_export_check(state)

    check = _export_check()
    assert check is not None
    assert check["status"] == "missing"
    assert not (tmp_path / "never-created.db").exists(), "a read-only check created the database"


def test_a_database_without_a_sessions_table_is_a_missing_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from studyloop.session.cleanup import record_harness_export_check

    bare = tmp_path / "bare.db"
    sqlite3.connect(bare).close()
    monkeypatch.setenv("STUDYLOOP_DB", str(bare))
    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    state = _pi_state(session_dir)

    record_harness_export_check(state)

    check = _export_check()
    assert check is not None
    assert check["status"] == "missing"


def test_only_a_row_from_a_previous_run_is_a_missing_export(db: Path, tmp_path: Path) -> None:
    """A row for the same session dir that predates this start is last time's export."""
    from studyloop.session.cleanup import record_harness_export_check

    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    _insert_pi_row(db, session_dir, _BEFORE)
    state = _pi_state(session_dir)

    record_harness_export_check(state)

    check = _export_check()
    assert check is not None
    assert check["status"] == "missing"


def test_a_row_naming_the_physical_path_matches_a_symlinked_session_dir(
    db: Path, tmp_path: Path
) -> None:
    """node's ``process.cwd()`` is the physical path; the sessions dir may be a symlink."""
    from studyloop.session.cleanup import record_harness_export_check

    physical = tmp_path / "volumes" / "base" / "tries"
    physical.mkdir(parents=True)
    link_parent = tmp_path / "config" / "sessions"
    link_parent.mkdir(parents=True)
    link = link_parent / "tries"
    link.symlink_to(physical, target_is_directory=True)
    _insert_pi_row(db, physical, _AFTER)
    state = _pi_state(link)

    record_harness_export_check(state)

    check = _export_check()
    assert check is not None
    assert check["status"] == "ok"


def test_another_harness_records_no_export_check(db: Path, tmp_path: Path) -> None:
    from studyloop.session.cleanup import record_harness_export_check

    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    _insert_pi_row(db, session_dir, _AFTER)
    state = _pi_state(session_dir, agent="claude")

    record_harness_export_check(state)

    assert "export_check" not in session_state.read_session_state()


def test_cleanup_on_exit_records_the_check_before_teardown_kills_the_pane(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_cleanup_tmux_and_files`` kills the tmux session this code runs in.

    The SIGHUP stand-in is a ``SystemExit`` from that step: whatever the state
    file holds at that moment is all the dashboard will ever see.
    """
    from studyloop.session import cleanup

    session_dir = tmp_path / "sessions" / "tries"
    session_dir.mkdir(parents=True)
    _pi_state(session_dir)  # no pi row: the verdict must be "missing", and must be there

    def _pane_killed(*_args: object, **_kwargs: object) -> None:
        raise SystemExit(129)

    monkeypatch.setattr(cleanup, "_cleanup_tmux_and_files", _pane_killed)
    monkeypatch.setattr(cleanup, "_teardown_agent", lambda _state: None)
    monkeypatch.setattr(cleanup, "_kill_background_processes", lambda _state: None)

    with pytest.raises(SystemExit):
        cleanup.cleanup_on_exit()

    check = _export_check()
    assert check is not None, "the export check did not run before the pane was killed"
    assert check["status"] == "missing"
    assert session_state.read_session_state().get("mode") == "ended"


# ---------------------------------------------------------------------------
# The dashboard's ended view: one line when the export is missing
# ---------------------------------------------------------------------------

_MISSING_LINE = (
    "This pi session was not exported to the session database — run `session-export --pi-only`."
)


def _ended_state(export_check: dict | None) -> dict:
    state = {
        "study_session_id": "study-1",
        "mode": "ended",
        "agent": "pi",
        "topic": "Tries",
        "topics": [{"status": "win", "topic": "Prefix trees", "note": ""}],
        "parking": [],
    }
    if export_check is not None:
        state["export_check"] = export_check
    return state


def test_the_ended_view_says_when_the_pi_export_is_missing() -> None:
    from studyloop.web.routes.session._render import _render_update

    html = _render_update(
        _ended_state({"harness": "pi", "status": "missing", "checked_at": _AFTER})
    )

    assert "Session Complete" in html
    assert _MISSING_LINE in html, html
    assert html.count("session-export --pi-only") == 1, "the line is shown once"


@pytest.mark.parametrize(
    "export_check",
    [None, {"harness": "pi", "status": "ok", "checked_at": _AFTER}],
    ids=["no-check", "ok"],
)
def test_the_ended_view_is_silent_when_the_export_is_fine(export_check: dict | None) -> None:
    from studyloop.web.routes.session._render import _render_update

    html = _render_update(_ended_state(export_check))

    assert "Session Complete" in html
    assert "session-export" not in html
