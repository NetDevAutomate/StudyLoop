"""Tests for agent_session_tools.tiering — hot/full DB tiering.

Covers the safety invariants:
- FTS integrity check + repair (the 45GB-bug guardrail)
- compact_database rescues real data and dedups the FTS index
- sync_to_full is idempotent (re-running syncs nothing new)
- prune_hot never deletes a session missing from the full DB
- snapshot rotation and mount-safety directory guard
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools import tiering
from agent_session_tools.export_sessions import init_db
from agent_session_tools.tiering import (
    CompactStats,
    FtsIntegrity,
    compact_database,
    create_snapshot,
    ensure_leaf_dir,
    fts_integrity,
    get_full_db_path,
    prune_hot,
    repair_fts,
    sync_to_full,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hot_db(path: Path, sessions: int = 3, days_old: int = 0) -> None:
    """Create a migrated DB with N sessions of 2 messages each."""
    conn = init_db(str(path))
    ts = (datetime.now() - timedelta(days=days_old)).isoformat()
    for i in range(sessions):
        conn.execute(
            "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
            "VALUES (?, 'claude_code', ?, ?, ?)",
            (f"s{i}", ts, ts, f"hash{i}"),
        )
        for j in range(2):
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp) "
                "VALUES (?, ?, 'user', ?, ?)",
                (f"s{i}-m{j}", f"s{i}", f"message {i}-{j} about decorators", ts),
            )
    conn.commit()
    conn.close()


def _counts(path: Path) -> tuple[int, int, int]:
    conn = sqlite3.connect(path)
    try:
        s = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        f = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        return s, m, f
    finally:
        conn.close()


@pytest.fixture
def tiered_config(tmp_path, monkeypatch):
    """Config with hot + full paths inside tmp_path, active via STUDYLOOP_CONFIG."""
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
        f"""
database:
  path: {hot}
  backup_dir: {backup_dir}
  full_db_path: {full}
  snapshot_retention: 2
"""
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))
    return {
        "hot": hot,
        "full": full,
        "backup_dir": backup_dir,
        "config_dir": config_dir,
    }


# ---------------------------------------------------------------------------
# FTS integrity + repair
# ---------------------------------------------------------------------------


class TestFtsIntegrity:
    def test_healthy_index(self, tmp_path):
        db = tmp_path / "db.sqlite"
        _make_hot_db(db, sessions=2)
        conn = sqlite3.connect(db)
        result = fts_integrity(conn)
        conn.close()
        assert result.healthy
        assert result.drift == 0
        assert result.fts_rows == 4

    def test_detects_duplication_bug(self, tmp_path):
        """Simulate the 45GB bug: bulk re-insert of the whole index."""
        db = tmp_path / "db.sqlite"
        _make_hot_db(db, sessions=2)
        conn = sqlite3.connect(db)
        # The historical bug: unconditional bulk insert on every export run
        for _ in range(3):
            conn.execute(
                "INSERT INTO messages_fts(content, session_id, role) "
                "SELECT content, session_id, role FROM messages"
            )
        conn.commit()
        result = fts_integrity(conn)
        assert not result.healthy
        assert result.fts_rows == 16  # 4 real + 3 bulk copies of 4
        assert result.drift == 12

        repaired = repair_fts(conn)
        assert repaired.healthy
        assert repaired.fts_rows == 4
        # Search still works after repair
        hits = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'decorators'"
        ).fetchone()[0]
        conn.close()
        assert hits == 4

    def test_drift_dataclass_properties(self):
        assert FtsIntegrity(10, 10).healthy
        assert FtsIntegrity(10, 12).drift == 2
        assert not FtsIntegrity(10, 8).healthy


# ---------------------------------------------------------------------------
# compact_database (rescue)
# ---------------------------------------------------------------------------


class TestCompact:
    def test_rescues_data_and_dedups_fts(self, tmp_path):
        source = tmp_path / "bloated.db"
        _make_hot_db(source, sessions=3)
        conn = sqlite3.connect(source)
        for _ in range(5):  # bloat the index 5x
            conn.execute(
                "INSERT INTO messages_fts(content, session_id, role) "
                "SELECT content, session_id, role FROM messages"
            )
        conn.commit()
        conn.close()

        dest = tmp_path / "clean" / "sessions_full.db"
        dest.parent.mkdir()
        stats = compact_database(source, dest)

        assert isinstance(stats, CompactStats)
        assert stats.tables_copied["sessions"] == 3
        assert stats.tables_copied["messages"] == 6
        assert stats.fts is not None and stats.fts.healthy
        s, m, f = _counts(dest)
        assert (s, m, f) == (3, 6, 6)

    def test_source_never_modified(self, tmp_path):
        source = tmp_path / "bloated.db"
        _make_hot_db(source, sessions=1)
        before = source.read_bytes()
        dest = tmp_path / "clean.db"
        compact_database(source, dest)
        assert source.read_bytes() == before

    def test_refuses_existing_dest(self, tmp_path):
        source = tmp_path / "src.db"
        _make_hot_db(source, sessions=1)
        dest = tmp_path / "dest.db"
        dest.write_bytes(b"precious")
        with pytest.raises(FileExistsError):
            compact_database(source, dest)
        assert dest.read_bytes() == b"precious"

    def test_missing_source(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compact_database(tmp_path / "nope.db", tmp_path / "out.db")


# ---------------------------------------------------------------------------
# sync_to_full (incremental)
# ---------------------------------------------------------------------------


class TestSyncToFull:
    def test_initial_sync_copies_everything(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=3)
        stats = sync_to_full()
        assert stats.sessions_synced == 3
        assert stats.messages_synced == 6
        assert _counts(tiered_config["full"]) == (3, 6, 6)

    def test_idempotent(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=2)
        sync_to_full()
        again = sync_to_full()
        assert again.sessions_synced == 0
        assert again.messages_synced == 0
        assert _counts(tiered_config["full"]) == (2, 4, 4)

    def test_changed_session_resynced_without_fts_bloat(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=2)
        sync_to_full()

        # Session s0 gains a message and a new content hash
        conn = sqlite3.connect(tiered_config["hot"])
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) "
            "VALUES ('s0-m9', 's0', 'assistant', 'new reply')"
        )
        conn.execute("UPDATE sessions SET content_hash='hash0-v2' WHERE id='s0'")
        conn.commit()
        conn.close()

        stats = sync_to_full()
        assert stats.sessions_synced == 1
        s, m, f = _counts(tiered_config["full"])
        assert (s, m) == (2, 5)
        assert f == m  # FTS invariant preserved by triggers

    def test_full_survives_hot_deletion(self, tiered_config):
        """The point of tiering: pruning hot never shrinks full."""
        _make_hot_db(tiered_config["hot"], sessions=3)
        sync_to_full()
        conn = sqlite3.connect(tiered_config["hot"])
        conn.execute("DELETE FROM messages WHERE session_id='s0'")
        conn.execute("DELETE FROM sessions WHERE id='s0'")
        conn.commit()
        conn.close()
        sync_to_full()
        assert _counts(tiered_config["full"])[0] == 3

    def test_unconfigured_raises(self, tiered_config, monkeypatch):
        cfg_file = tiered_config["config_dir"] / "config.yaml"
        cfg_file.write_text(f"database:\n  path: {tiered_config['hot']}\n")
        _make_hot_db(tiered_config["hot"], sessions=1)
        with pytest.raises(ValueError, match="full_db_path"):
            sync_to_full()


# ---------------------------------------------------------------------------
# prune_hot (verify-then-delete)
# ---------------------------------------------------------------------------


class TestPrune:
    def test_dry_run_by_default_deletes_nothing(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=3, days_old=60)
        sync_to_full()
        stats = prune_hot(days=30)
        assert stats.dry_run
        assert stats.verified == 3
        assert _counts(tiered_config["hot"])[0] == 3  # nothing deleted

    def test_deletes_verified_old_sessions(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=3, days_old=60)
        sync_to_full()
        stats = prune_hot(days=30, dry_run=False)
        assert stats.sessions_deleted == 3
        assert stats.messages_deleted == 6
        s, m, f = _counts(tiered_config["hot"])
        assert (s, m, f) == (0, 0, 0)  # FTS cleaned by triggers
        assert _counts(tiered_config["full"]) == (3, 6, 6)  # full untouched

    def test_never_deletes_unverified_sessions(self, tiered_config):
        """THE invariant: not in full DB -> not deleted, ever."""
        _make_hot_db(tiered_config["hot"], sessions=3, days_old=60)
        sync_to_full()
        # s2 changes AFTER the sync — full now holds a stale hash for it
        conn = sqlite3.connect(tiered_config["hot"])
        conn.execute("UPDATE sessions SET content_hash='changed' WHERE id='s2'")
        conn.commit()
        conn.close()

        stats = prune_hot(days=30, dry_run=False)
        assert stats.sessions_deleted == 2
        assert stats.skipped_unverified == 1
        assert stats.skipped_ids == ["s2"]
        conn = sqlite3.connect(tiered_config["hot"])
        remaining = {r[0] for r in conn.execute("SELECT id FROM sessions")}
        conn.close()
        assert remaining == {"s2"}

    def test_recent_sessions_kept(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=2, days_old=5)
        sync_to_full()
        stats = prune_hot(days=30, dry_run=False)
        assert stats.candidates == 0
        assert _counts(tiered_config["hot"])[0] == 2

    def test_refuses_without_full_db_file(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1, days_old=60)
        # full DB never created (no sync ran)
        with pytest.raises(FileNotFoundError, match="sync-full"):
            prune_hot(days=30, dry_run=False)

    def test_learning_tables_untouched(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1, days_old=60)
        conn = sqlite3.connect(tiered_config["hot"])
        # study_progress is created by migrations; populate a row and verify
        # prune leaves it alone.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(study_progress)")]
        assert {"topic", "concept", "confidence"} <= set(cols)
        conn.execute(
            "INSERT INTO study_progress (topic, concept, confidence, first_seen, last_seen) "
            "VALUES ('python', 'decorators', 'learning', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()
        sync_to_full()
        prune_hot(days=30, dry_run=False)
        conn = sqlite3.connect(tiered_config["hot"])
        rows = conn.execute("SELECT COUNT(*) FROM study_progress").fetchone()[0]
        conn.close()
        assert rows == 1


@pytest.fixture
def _restore_tz():
    """R-20: change the process TZ for a test, then restore it. `datetime.now()`
    (no tz) reads the OS local-time setting, which only takes effect after
    `time.tzset()` on POSIX -- exactly the mechanism the naive-cutoff bug rode on.
    """
    original = os.environ.get("TZ")

    def _set(tz: str) -> None:
        os.environ["TZ"] = tz
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


class TestPruneUtcCutoff:
    """R-20 / D2: prune's cutoff must be real UTC, not local wall time."""

    @pytest.mark.parametrize("tz", ["Pacific/Auckland", "America/Los_Angeles"])
    def test_minute_inside_kept_minute_outside_pruned(
        self, tz, tiered_config, _restore_tz
    ):
        _make_hot_db(tiered_config["hot"], sessions=2)
        sync_to_full()

        days = 1
        cutoff_instant = datetime.now(UTC) - timedelta(days=days)
        inside = (cutoff_instant + timedelta(minutes=1)).isoformat()
        outside = (cutoff_instant - timedelta(minutes=1)).isoformat()

        conn = sqlite3.connect(tiered_config["hot"])
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = 's0'", (inside,))
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = 's1'", (outside,))
        conn.commit()
        conn.close()

        _restore_tz(tz)
        prune_hot(days=days, dry_run=False)

        remaining = {
            r[0]
            for r in sqlite3.connect(tiered_config["hot"]).execute(
                "SELECT id FROM sessions"
            )
        }
        assert "s0" in remaining, (
            f"a session 1 minute inside the UTC cutoff must survive under TZ={tz}"
        )
        assert "s1" not in remaining, (
            f"a session 1 minute outside the UTC cutoff must be pruned under TZ={tz}"
        )


# ---------------------------------------------------------------------------
# Snapshots + rotation
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_creates_and_rotates(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()
        made = []
        with patch("agent_session_tools.tiering.datetime") as mock_dt:
            for i in range(4):  # retention is 2 in the fixture config
                mock_dt.now.return_value = datetime(2026, 7, 26, 12, 0, i)
                made.append(create_snapshot())
        snapshots = sorted(tiered_config["backup_dir"].glob("*_snapshot_*.db"))
        assert len(snapshots) == 2
        assert snapshots[-1] == made[-1]

    def test_snapshot_is_valid_db(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=2)
        sync_to_full()
        snap = create_snapshot()
        assert _counts(snap) == (2, 4, 4)


# ---------------------------------------------------------------------------
# Mount-safety + config helpers
# ---------------------------------------------------------------------------


class TestGuards:
    def test_ensure_leaf_dir_refuses_missing_parent(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="mounted"):
            ensure_leaf_dir(tmp_path / "not_mounted" / "StudyLoop" / "DB")

    def test_ensure_leaf_dir_creates_leaf(self, tmp_path):
        target = tmp_path / "leaf"
        ensure_leaf_dir(target)
        assert target.is_dir()

    def test_get_full_db_path_disabled_by_default(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("database:\n  path: /tmp/x.db\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
        assert get_full_db_path() is None


# ---------------------------------------------------------------------------
# Daily trigger
# ---------------------------------------------------------------------------


class TestSyncTrigger:
    def test_noop_when_tiering_disabled(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("database:\n  path: /tmp/x.db\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
        assert tiering.maybe_spawn_sync() is False

    def test_always_mode_spawns_every_trigger(self, tiered_config, monkeypatch):
        """Default cadence: every export triggers a sync (record trails by seconds)."""
        marker = tiered_config["config_dir"] / ".last_full_sync"
        marker.write_text(date.today().isoformat())  # marker must be ignored
        lock = tiered_config["config_dir"] / ".full_sync.lock"
        monkeypatch.setattr(tiering, "_marker_path", lambda: marker)
        monkeypatch.setattr(tiering, "_lock_path", lambda: lock)
        with patch("agent_session_tools.tiering.subprocess.Popen") as popen:
            assert tiering.maybe_spawn_sync() is True
            assert tiering.maybe_spawn_sync() is True
            assert popen.call_count == 2

    def test_daily_mode_marker_prevents_second_run(self, tiered_config, monkeypatch):
        config_file = tiered_config["config_dir"] / "config.yaml"
        config_file.write_text(config_file.read_text() + "  sync_mode: daily\n")
        marker = tiered_config["config_dir"] / ".last_full_sync"
        marker.write_text(date.today().isoformat())
        monkeypatch.setattr(tiering, "_marker_path", lambda: marker)
        assert tiering.maybe_spawn_sync() is False

    def test_daily_mode_spawns_when_due(self, tiered_config, monkeypatch):
        config_file = tiered_config["config_dir"] / "config.yaml"
        config_file.write_text(config_file.read_text() + "  sync_mode: daily\n")
        marker = tiered_config["config_dir"] / ".last_full_sync"
        lock = tiered_config["config_dir"] / ".full_sync.lock"
        monkeypatch.setattr(tiering, "_marker_path", lambda: marker)
        monkeypatch.setattr(tiering, "_lock_path", lambda: lock)
        with patch("agent_session_tools.tiering.subprocess.Popen") as popen:
            assert tiering.maybe_spawn_sync() is True
            popen.assert_called_once()
            args = popen.call_args[0][0]
            assert "sync-full" in args
            assert popen.call_args[1]["start_new_session"] is True

    def test_no_spawn_while_lock_held(self, tiered_config, monkeypatch):
        lock = tiered_config["config_dir"] / ".full_sync.lock"
        lock.write_text("999")
        monkeypatch.setattr(tiering, "_lock_path", lambda: lock)
        with patch("agent_session_tools.tiering.subprocess.Popen") as popen:
            assert tiering.maybe_spawn_sync() is False
            popen.assert_not_called()

    def test_no_spawn_when_volume_unmounted(self, tiered_config, monkeypatch):
        """Mount-safety: unmounted volume -> quiet skip, no spawn."""
        config_file = tiered_config["config_dir"] / "config.yaml"
        config_file.write_text(
            config_file.read_text().replace(
                str(tiered_config["full"]),
                str(tiered_config["full"].parent.parent / "gone" / "DB" / "f.db"),
            )
        )
        import shutil

        shutil.rmtree(tiered_config["full"].parent.parent)
        with patch("agent_session_tools.tiering.subprocess.Popen") as popen:
            assert tiering.maybe_spawn_sync() is False
            popen.assert_not_called()

    def test_lock_prevents_concurrent_sync(self, tiered_config, monkeypatch):
        lock = tiered_config["config_dir"] / ".full_sync.lock"
        monkeypatch.setattr(tiering, "_lock_path", lambda: lock)
        assert tiering.acquire_sync_lock() is True
        assert tiering.acquire_sync_lock() is False
        tiering.release_sync_lock()
        assert tiering.acquire_sync_lock() is True
        tiering.release_sync_lock()

    def test_stale_lock_is_broken(self, tiered_config, monkeypatch):
        lock = tiered_config["config_dir"] / ".full_sync.lock"
        monkeypatch.setattr(tiering, "_lock_path", lambda: lock)
        lock.write_text("12345")
        old = datetime.now().timestamp() - 7200
        os.utime(lock, (old, old))
        assert tiering.acquire_sync_lock() is True
        tiering.release_sync_lock()


class TestOfflineCatchUp:
    def test_first_sync_after_remount_catches_up_everything(self, tiered_config):
        """Store-and-forward: the diff is stateless, so sessions accumulated
        while the volume was unavailable all land on the next sync."""
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()

        # "Offline" period: three more sessions land in hot, no sync runs.
        conn = sqlite3.connect(tiered_config["hot"])
        for i in range(10, 13):
            conn.execute(
                "INSERT INTO sessions (id, source, created_at, updated_at, "
                "content_hash) VALUES (?, 'kiro_cli', '2026-07-01', "
                "'2026-07-01', ?)",
                (f"off{i}", f"offhash{i}"),
            )
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content) "
                "VALUES (?, ?, 'user', 'offline work')",
                (f"off{i}-m0", f"off{i}"),
            )
        conn.commit()
        conn.close()

        # "Remount" + next trigger:
        stats = sync_to_full()
        assert stats.sessions_synced == 3
        assert _counts(tiered_config["full"])[0] == 4


class TestAutoSnapshot:
    def test_snapshot_created_when_none_exists(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()
        snap = tiering.maybe_snapshot()
        assert snap is not None and snap.exists()

    def test_no_snapshot_within_interval(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()
        first = tiering.maybe_snapshot()
        assert first is not None
        assert tiering.maybe_snapshot() is None  # fresh snapshot exists

    def test_snapshot_when_stale(self, tiered_config):
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()
        first = tiering.maybe_snapshot()
        assert first is not None
        old = datetime.now().timestamp() - 8 * 86400
        os.utime(first, (old, old))
        second = tiering.maybe_snapshot()
        assert second is not None and second != first

    def test_interval_zero_disables(self, tiered_config):
        config_file = tiered_config["config_dir"] / "config.yaml"
        config_file.write_text(
            config_file.read_text() + "  snapshot_interval_days: 0\n"
        )
        _make_hot_db(tiered_config["hot"], sessions=1)
        sync_to_full()
        assert tiering.maybe_snapshot() is None


class TestRefocus:
    def _seed(self, tiered_config):
        """Hot: 2 old python sessions + 1 old terraform + 1 recent terraform.
        Full additionally holds an old 'sql' session pruned from hot."""
        hot = tiered_config["hot"]
        conn = init_db(str(hot))
        old = (datetime.now() - timedelta(days=60)).isoformat()
        recent = (datetime.now() - timedelta(days=2)).isoformat()
        rows = [
            ("py1", old, "python decorators lesson"),
            ("py2", old, "python generators deep dive"),
            ("tf1", old, "terraform state locking"),
            ("tf2", recent, "terraform providers"),
        ]
        for sid, ts, content in rows:
            conn.execute(
                "INSERT INTO sessions (id, source, created_at, updated_at, "
                "content_hash) VALUES (?, 'claude_code', ?, ?, ?)",
                (sid, ts, ts, f"h-{sid}"),
            )
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp) "
                "VALUES (?, ?, 'user', ?, ?)",
                (f"{sid}-m0", sid, content, ts),
            )
        conn.commit()
        conn.close()
        sync_to_full()

        # A recent sql session exists ONLY in full (was pruned from hot).
        full_conn = sqlite3.connect(tiered_config["full"])
        sql_ts = (datetime.now() - timedelta(days=5)).isoformat()
        full_conn.execute(
            "INSERT INTO sessions (id, source, created_at, updated_at, "
            "content_hash) VALUES ('sql1', 'kiro_cli', ?, ?, 'h-sql1')",
            (sql_ts, sql_ts),
        )
        full_conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) "
            "VALUES ('sql1-m0', 'sql1', 'user', 'sql window functions practice', ?)",
            (sql_ts,),
        )
        full_conn.commit()
        full_conn.close()

    def test_pull_then_prune(self, tiered_config):
        self._seed(tiered_config)
        stats = tiering.refocus(["python", "sql"], days=30)

        # Pulled: sql1 (focus match, recent, missing from hot)
        assert stats.pulled_sessions == 1
        conn = sqlite3.connect(tiered_config["hot"])
        ids = {r[0] for r in conn.execute("SELECT id FROM sessions")}
        conn.close()
        # py1/py2 kept (focus match, despite age); tf1 pruned (old, no match);
        # tf2 kept (recent); sql1 pulled in.
        assert ids == {"py1", "py2", "tf2", "sql1"}
        assert stats.prune is not None
        assert stats.prune.sessions_deleted == 1
        # Hot FTS invariant survives the pull+prune round trip
        conn = sqlite3.connect(tiered_config["hot"])
        integrity = fts_integrity(conn)
        conn.close()
        assert integrity.healthy

    def test_dry_run_moves_nothing(self, tiered_config):
        self._seed(tiered_config)
        before = _counts(tiered_config["hot"])
        stats = tiering.refocus(["python"], days=30, dry_run=True)
        assert stats.dry_run
        assert _counts(tiered_config["hot"]) == before
        assert stats.pulled_sessions == 0  # nothing new matches python in full only

    def test_unmounted_full_raises_with_guidance(self, tiered_config):
        self._seed(tiered_config)
        tiered_config["full"].unlink()
        with pytest.raises(FileNotFoundError, match="focus apply"):
            tiering.refocus(["python"], days=30)

    def test_requires_topics(self, tiered_config):
        self._seed(tiered_config)
        with pytest.raises(ValueError, match="topic"):
            tiering.refocus([], days=30)

    def test_topics_fts_query_quotes_phrases(self):
        q = tiering.topics_fts_query(["sql window functions", "python"])
        assert q == '"sql window functions" OR "python"'
        # FTS operators / quotes in topic names are neutralised by quoting
        assert tiering.topics_fts_query(['a"b']) == '"a b"'
