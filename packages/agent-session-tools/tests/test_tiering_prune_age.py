"""`prune_hot` ages a session the way `session-maint delete` does (F-AST-06).

Plan 5, lane Q, larger #2 item 6 (lane 4's found-not-fixed #6). `prune_hot`
selected its candidates with ``updated_at < ? OR updated_at IS NULL``, so a
session whose ``updated_at`` is NULL -- every Kiro v1 conversation, and any
harness that gave none -- was "older than N days" however new it was, while
delete and archive had already moved to the age rule
``COALESCE(updated_at, created_at, MAX(messages.timestamp))`` with an unknown
age kept and counted (601863e8). Prune's full-DB verification and
anchored-session exclusion bounded the damage (a recent session is in full
after a sync, so it was evicted from hot, not lost), but eviction of a
session the learner used yesterday is still wrong. Same rule, same counting.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from agent_session_tools.export_sessions import init_db
from agent_session_tools.maintenance import app
from agent_session_tools.tiering import prune_hot, sync_to_full

runner = CliRunner()


@pytest.fixture
def tiered_config(tmp_path, monkeypatch):
    """Hot + full inside tmp_path, active via STUDYLOOP_CONFIG (as test_tiering)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external" / "DB"
    full_dir.mkdir(parents=True)
    full = full_dir / "sessions_full.db"
    backup_dir = tmp_path / "external" / "Backups"
    backup_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text(
        f"database:\n  path: {hot}\n  backup_dir: {backup_dir}\n  full_db_path: {full}\n"
        f"logging:\n  path: {tmp_path / 'sessions.log'}\n  level: INFO\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))
    return {"hot": hot, "full": full}


def _seed(hot) -> None:
    """Five sessions whose age is known five different ways (or not at all)."""
    conn = init_db(str(hot))
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    rows = [
        # id, created_at, updated_at, message timestamp
        ("dated-old", old, old, old),
        ("undated-old-created", old, None, None),
        ("undated-recent-created", recent, None, None),
        ("undated-recent-message", None, None, recent),
        ("unknown-age", None, None, None),
    ]
    for sid, created, updated, stamp in rows:
        conn.execute(
            "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
            "VALUES (?, 'kiro_cli', ?, ?, ?)",
            (sid, created, updated, f"h-{sid}"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) "
            "VALUES (?, ?, 'user', ?, ?)",
            (f"{sid}-m0", sid, f"notes for {sid}", stamp),
        )
    conn.commit()
    conn.close()


def _ids(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM sessions")}
    finally:
        conn.close()


class TestPruneAgeRule:
    def test_a_recent_session_with_null_updated_at_is_not_a_candidate(
        self, tiered_config
    ):
        _seed(tiered_config["hot"])
        sync_to_full()

        stats = prune_hot(days=30, dry_run=False)

        assert stats.candidates == 2
        assert stats.sessions_deleted == 2
        assert _ids(tiered_config["hot"]) == {
            "undated-recent-created",
            "undated-recent-message",
            "unknown-age",
        }
        # Full keeps everything, as always.
        assert len(_ids(tiered_config["full"])) == 5

    def test_a_session_of_unknown_age_is_kept_and_counted(self, tiered_config):
        _seed(tiered_config["hot"])
        sync_to_full()

        stats = prune_hot(days=30, dry_run=True)

        assert stats.skipped_undated == 1
        assert "unknown-age" not in stats.skipped_ids
        assert stats.candidates == 2

    def test_created_at_ages_a_session_whose_updated_at_is_null(self, tiered_config):
        """The old predicate happened to select this one too; the new rule must
        still select it, for its created_at rather than for its NULL."""
        _seed(tiered_config["hot"])
        sync_to_full()

        stats = prune_hot(days=30, dry_run=False)

        assert "undated-old-created" not in _ids(tiered_config["hot"])
        assert stats.verified == 2

    def test_dry_run_reports_the_same_candidates(self, tiered_config):
        _seed(tiered_config["hot"])
        sync_to_full()

        stats = prune_hot(days=30)

        assert stats.dry_run
        assert stats.candidates == 2
        assert stats.verified == 2
        assert len(_ids(tiered_config["hot"])) == 5


class TestPruneCliReportsUnknownAge:
    def test_prune_prints_the_kept_undated_count(self, tiered_config, monkeypatch):
        _seed(tiered_config["hot"])
        sync_to_full()
        import agent_session_tools.maintenance as maintenance

        monkeypatch.setattr(maintenance, "_config", None)

        result = runner.invoke(app, ["prune", "--days", "30"])

        assert result.exit_code == 0, result.output
        assert "Candidates older than 30 days: 2" in result.output
        assert "1 session(s) with no timestamp" in result.output
