"""Real annotation commands must retain history and reject stale editor saves."""

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools.context import annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from agent_session_tools.query_sessions import app

runner = CliRunner()


@pytest.fixture
def cli_db(migrated_db, tmp_path, monkeypatch):
    conn, db = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    config = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": ["/fixture/p"]},
                "w": {"scope": "work", "roots": ["/fixture/w"]},
            },
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    conn.executemany(
        "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
        [
            ("personal", "kiro_cli", "/fixture/p"),
            ("work", "kiro_cli", "/fixture/w"),
        ],
    )
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) VALUES ('personal','original')"
    )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="test", dry_run=False)
    return conn, db


def command(db, *args):
    return runner.invoke(app, [*args, "--db", str(db)])


def test_note_correction_retains_unattributed_prior_value(cli_db):
    conn, db = cli_db
    result = command(db, "note", "personal", "--text", "corrected")
    assert result.exit_code == 0, result.output
    state = annotations.snapshot(conn, "personal")
    assert annotations.values(state) == [{"notes": "corrected"}]
    assert len(state.history) == 2
    assert {r["payload"]["notes"] for r in state.history} == {"original", "corrected"}
    assert all(
        r["source_relationship"] == "about_session" and r["sources"] == []
        for r in state.history
    )
    assert not conn.execute("SELECT 1 FROM session_notes").fetchone()
    conn.rollback()
    result = command(db, "note", "personal", "--history")
    assert result.exit_code == 0
    view = json.loads(result.output)
    assert view["version_count"] == 2 and view["current_count"] == 1


def test_editor_scope_change_does_not_save_or_leave_tempfile(cli_db, monkeypatch):
    conn, db = cli_db
    paths = []

    def editor(command_args, **kwargs):
        path = Path(command_args[-1])
        paths.append(path)
        path.write_text("should not be saved")
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")

    monkeypatch.setattr("agent_session_tools.query_sessions.subprocess.run", editor)
    result = command(db, "note", "personal", "--edit")
    assert result.exit_code == 1 and "saved" not in result.output.lower()
    assert (
        conn.execute(
            "SELECT notes FROM session_notes WHERE session_id='personal'"
        ).fetchone()[0]
        == "original"
    )
    assert not conn.execute("SELECT 1 FROM context_observations").fetchone()
    assert paths and not any(p.exists() for p in paths)


def test_editor_releases_locks_and_detects_concurrent_version(cli_db, monkeypatch):
    conn, db = cli_db

    def editor(command_args, **kwargs):
        other = records.connect(db)
        try:
            with ContextStore(other)._atomic(), records.policy_guard(other):
                annotations.write(
                    other, "personal", "note", {"notes": "concurrent correction"}
                )
        finally:
            other.close()
        Path(command_args[-1]).write_text("stale editor value")

    monkeypatch.setattr("agent_session_tools.query_sessions.subprocess.run", editor)
    result = command(db, "note", "personal", "--edit")
    assert result.exit_code == 1 and "changed while editing" in result.output
    assert annotations.values(annotations.snapshot(conn, "personal")) == [
        {"notes": "concurrent correction"}
    ]


def test_editor_detects_assignment_away_and_back(cli_db, monkeypatch):
    conn, db = cli_db

    def editor(command_args, **kwargs):
        other = records.connect(db)
        try:
            for project in ("w", "p"):
                other.execute(
                    "UPDATE context_session_projects SET project_id=? WHERE session_id='personal'",
                    (project,),
                )
                other.commit()
        finally:
            other.close()
        Path(command_args[-1]).write_text("stale value")

    monkeypatch.setattr("agent_session_tools.query_sessions.subprocess.run", editor)
    result = command(db, "note", "personal", "--edit")
    assert result.exit_code == 1 and "changed while editing" in result.output
    assert (
        conn.execute(
            "SELECT notes FROM session_notes WHERE session_id='personal'"
        ).fetchone()[0]
        == "original"
    )


def test_tags_keep_conflicting_versions_until_explicit_update(cli_db):
    conn, db = cli_db
    assert command(db, "tag", "personal", "--add", "first").exit_code == 0
    ObservationStore(conn).append(
        kind=annotations.KINDS["tags"],
        subject="personal",
        payload={"tags": ["second"]},
        producer="peer",
        authority="reported",
        owner_session_id="personal",
    )
    result = command(db, "tag", "personal")
    assert "Conflicting current tag reports" in result.output
    assert "first" in result.output and "second" in result.output
    assert command(db, "tag", "personal", "--remove", "first").exit_code == 0
    assert annotations.values(annotations.snapshot(conn, "personal", "tags")) == [
        {"tags": ["second"]}
    ]


def test_forgotten_annotation_does_not_reappear_from_old_shadow(cli_db):
    conn, db = cli_db
    assert command(db, "note", "personal", "--text", "new note").exit_code == 0
    state = annotations.snapshot(conn, "personal")
    conn.rollback()
    assert ObservationStore(conn).forget(state.current[0]["id"])
    with pytest.raises(sqlite3.IntegrityError, match="forgotten"):
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES ('personal','stale replica')"
        )
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM session_notes").fetchone()[0] == 0
    assert annotations.values(annotations.snapshot(conn, "personal")) == []


def test_large_annotation_view_is_explicitly_partial(cli_db):
    conn, _ = cli_db
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        annotations.write(conn, "personal", "note", {"notes": "界" * 10000})
    result = annotations.view(conn, "personal", max_bytes=4096)
    assert (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        <= 4096
    )
    assert result["coverage"] == "partial" and result["current_count"] == 1
    assert all(not v["current"] for v in result["versions"])


@pytest.mark.parametrize(
    "kind,action",
    [
        ("note", ["note", "personal", "--text", "new"]),
        ("tags", ["tag", "personal", "--add", "new"]),
    ],
)
def test_policy_changes_inside_write_roll_back_every_version(
    cli_db, monkeypatch, kind, action
):
    conn, db = cli_db
    original = annotations.write

    def changing(*args, **kwargs):
        identity = original(*args, **kwargs)
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
        return identity

    monkeypatch.setattr(annotations, "write", changing)
    result = command(db, *action)
    assert result.exit_code == 1 and "saved" not in result.output.lower()
    assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0
    assert conn.execute("SELECT notes FROM session_notes").fetchone()[0] == "original"


def test_commit_failure_never_reports_success(cli_db, monkeypatch):
    conn, db = cli_db

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    failing = sqlite3.connect(db, factory=FailingCommit)
    failing.row_factory = sqlite3.Row
    failing.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr(
        "agent_session_tools.query_sessions._annotation_connection",
        lambda *a, **k: failing,
    )
    result = command(db, "note", "personal", "--text", "must roll back")
    assert result.exit_code != 0 and "saved" not in result.output.lower()
    assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0
    assert conn.execute("SELECT notes FROM session_notes").fetchone()[0] == "original"


def test_editor_cancellation_removes_private_tempfile(cli_db, monkeypatch):
    import subprocess

    conn, db = cli_db
    paths = []

    def cancel(args, **kwargs):
        path = Path(args[-1])
        paths.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("agent_session_tools.query_sessions.subprocess.run", cancel)
    result = command(db, "note", "personal", "--edit")
    assert result.exit_code == 1 and "saved" not in result.output.lower()
    assert paths and not any(p.exists() for p in paths)
    assert conn.execute("SELECT notes FROM session_notes").fetchone()[0] == "original"


def test_clear_is_an_explicit_idempotent_correction(cli_db):
    conn, db = cli_db
    for _ in range(2):
        assert command(db, "note", "personal", "--text", "").exit_code == 0
    state = annotations.snapshot(conn, "personal")
    assert annotations.values(state) == [{"notes": ""}]
    assert len(state.history) == 2


def test_conflicting_notes_require_explicit_correction(cli_db, monkeypatch):
    conn, db = cli_db
    assert command(db, "note", "personal", "--text", "first").exit_code == 0
    ObservationStore(conn).append(
        kind=annotations.KINDS["note"],
        subject="personal",
        payload={"notes": "second"},
        producer="peer",
        authority="reported",
        owner_session_id="personal",
    )
    monkeypatch.setattr(
        "agent_session_tools.query_sessions.subprocess.run",
        lambda *a, **k: pytest.fail("editor must not choose a winner"),
    )
    assert command(db, "note", "personal", "--edit").exit_code == 1
    assert command(db, "note", "personal", "--text", "reconciled").exit_code == 0
    state = annotations.snapshot(conn, "personal")
    assert annotations.values(state) == [{"notes": "reconciled"}]
    assert len(state.current[0]["supersedes"]) == 2
    assert len(state.history) == 4


def test_direct_retirement_invalidates_an_inflight_response(cli_db):
    from agent_session_tools.context.response import ScopeConflict, read_boundary

    conn, db = cli_db
    other = records.connect(db)
    try:
        with pytest.raises(ScopeConflict), read_boundary():
            assert annotations.view(conn, "personal")["legacy"]["notes"] == "original"
            other.execute(
                "INSERT INTO context_annotation_retirements VALUES ('personal','note')"
            )
            other.commit()
    finally:
        other.close()
        conn.rollback()
    assert annotations.view(conn, "personal")["legacy"] is None
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        conn.execute("DELETE FROM context_annotation_retirements")
    conn.rollback()


def test_direct_owner_removal_retires_legacy_and_observation(cli_db):
    conn, db = cli_db
    assert command(db, "note", "personal", "--text", "new").exit_code == 0
    identity = annotations.snapshot(conn, "personal").current[0]["id"]
    conn.rollback()
    conn.execute(
        "DELETE FROM context_observation_session_owners WHERE observation_id=?",
        (identity,),
    )
    conn.commit()
    assert conn.execute(
        "SELECT 1 FROM context_annotation_retirements WHERE session_id='personal' AND kind='note'"
    ).fetchone()
    assert annotations.values(annotations.snapshot(conn, "personal")) == []


def test_reserved_annotation_kind_cannot_claim_another_owner(cli_db):
    conn, _ = cli_db
    for owner in (None, "work"):
        with pytest.raises(ValueError, match="named session owner"):
            ObservationStore(conn).append(
                kind=annotations.KINDS["note"],
                subject="personal",
                payload={"notes": "misbound"},
                producer="fixture",
                authority="reported",
                owner_session_id=owner,
            )


def test_duplicate_detection_filters_owners_before_comparison(cli_db, monkeypatch):
    from agent_session_tools import deduplication as dedup

    conn, _ = cli_db
    conn.execute(
        "UPDATE sessions SET content_hash='same', updated_at='2026-09-06T12:00:00'"
    )
    conn.commit()
    assert dedup.find_duplicates(conn) == []
    with pytest.raises(ScopeError, match="unavailable in current scope"):
        dedup.calculate_message_similarity(conn, "personal", "work")
    conn.rollback()
    with pytest.raises(ScopeError, match="unavailable in current scope"):
        dedup.merge_duplicates(conn, "personal", ["work"])
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2


def test_classified_duplicates_are_retained_by_auto_merge(cli_db):
    from agent_session_tools import deduplication as dedup
    from agent_session_tools.context.scope import active_policy

    conn, _ = cli_db
    conn.execute(
        "INSERT INTO sessions(id,source,project_path,content_hash) VALUES ('personal2','kiro_cli','/fixture/p','same')"
    )
    conn.execute("UPDATE sessions SET content_hash='same' WHERE id='personal'")
    conn.commit()
    apply_policy(conn, active_policy(), actor="fixture", dry_run=False)
    stats = dedup.auto_merge_safe_duplicates(conn)
    assert stats["groups_protected"] == 1 and stats["sessions_removed"] == 0
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 3


def test_retired_predecessor_is_disclosed_as_incomplete_history(cli_db):
    conn, db = cli_db
    assert command(db, "note", "personal", "--text", "corrected").exit_code == 0
    state = annotations.snapshot(conn, "personal")
    predecessor = state.current[0]["supersedes"][0]
    conn.rollback()
    ObservationStore(conn).forget(predecessor)
    result = annotations.view(conn, "personal")
    current = next(v for v in result["versions"] if v["current"])
    assert current["history_incomplete"] is True and current["supersedes"] == []
    assert current["payload"]["notes"] == "corrected"
