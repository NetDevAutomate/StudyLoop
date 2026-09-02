"""R-19: cross-machine sync must gate every GLOBAL_SYNC_TABLES row on
``updated_at`` (like `sessions`/`messages` already do), and `push`/the remote
side of `sync` must back up the destination before writing to it, exactly as
`pull` already does.

Safety: every DB here is built fresh under `tmp_path` (via the `temp_db`/
`migrated_db` fixtures in conftest.py) or an explicit `tmp_path` backup_dir.
Nothing touches `~/.config/studyloop`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from agent_session_tools.migrations import migrate
from agent_session_tools.sync import (
    GLOBAL_TABLE_PRIMARY_KEYS,
    TABLE_SYNC_COLUMNS,
    _backup_destination,
    _build_global_upsert_select_sql,
    _dump_delta_sql,
    _stream_sql_to_target,
)


def _seed_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at) "
        "VALUES (?, 'test', '2024-01-01', '2024-01-01')",
        (session_id,),
    )


def _seed_study_progress(
    conn: sqlite3.Connection, progress_id: str, updated_at: str
) -> None:
    conn.execute(
        """
        INSERT INTO study_progress
            (id, topic, concept, confidence, first_seen, last_seen, updated_at)
        VALUES (?, 'python', 'decorators', 'learning', '2024-01-01', '2024-01-01', ?)
        """,
        (progress_id, updated_at),
    )


def _seed_knowledge_bridge(
    conn: sqlite3.Connection,
    sync_key: str,
    *,
    updated_at: str | None,
    quality: str = "proposed",
) -> None:
    """`knowledge_bridges.updated_at` is nullable (unlike `study_progress`'s
    NOT NULL column), which is exactly what R-19b's NULL-destination test
    needs to construct.

    Keyed by an explicit `sync_key` (R-19e), not `id` -- `id` is a
    per-machine AUTOINCREMENT counter and is no longer the sync conflict
    target (arbitration A5); two rows across "machines" that should be
    treated as the same logical row must share a `sync_key`, matching what
    migrate_v30's AFTER INSERT trigger would assign on the real write path.
    """
    conn.execute(
        """
        INSERT INTO knowledge_bridges
            (sync_key, source_concept, source_domain, target_concept, target_domain,
             quality, updated_at)
        VALUES (?, 'decorator', 'python', 'wrapper', 'general', ?, ?)
        """,
        (sync_key, quality, updated_at),
    )


class TestGlobalUpsertSql:
    """Shape of the generated SQL, independent of any DB."""

    def test_uses_conditional_upsert_not_blind_replace(self):
        sql = _build_global_upsert_select_sql("study_progress")
        assert "INSERT OR REPLACE" not in sql
        assert 'ON CONFLICT("id")' in sql
        # R-19b: COALESCE(dest, '') on the destination side only -- a NULL
        # destination must lose to any dated source; a NULL source must not
        # win (see TestRecencyGateEndToEnd::test_null_destination_loses_to_dated_source).
        assert (
            "WHERE excluded.\"updated_at\" > COALESCE(study_progress.\"updated_at\", '''')"
            in sql
        )

    def test_covers_every_global_table_and_pk(self):
        # Every GLOBAL_SYNC_TABLES entry (sync.py) has a primary/conflict key
        # and an updated_at column to gate on.
        from agent_session_tools.sync import GLOBAL_SYNC_TABLES

        for table in GLOBAL_SYNC_TABLES:
            assert table in GLOBAL_TABLE_PRIMARY_KEYS, table
            assert "updated_at" in TABLE_SYNC_COLUMNS[table], table
            # Must not raise (KeyError on a missing pk/column entry).
            _build_global_upsert_select_sql(table)


class TestRecencyGateEndToEnd:
    """Two fixture DBs, a real dump, a real apply -- proving R-19's DoD."""

    def _make_migrated_db(
        self, tmp_path: Path, name: str
    ) -> tuple[sqlite3.Connection, Path]:
        db_path = tmp_path / name
        conn = sqlite3.connect(db_path)
        schema_path = (
            Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
        )
        conn.executescript(schema_path.read_text())
        migrate(conn)
        conn.commit()
        return conn, db_path

    def test_newer_destination_row_survives_a_push(self, tmp_path):
        """The bug (D1): a stale source must not revert a newer destination row."""
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        _seed_study_progress(source_conn, "prog-1", updated_at="2024-01-01T00:00:00Z")
        source_conn.commit()

        _seed_session(dest_conn, "sess-1")
        _seed_study_progress(dest_conn, "prog-1", updated_at="2024-06-01T00:00:00Z")
        dest_conn.commit()
        dest_conn.close()

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert "ON CONFLICT" in sql  # sanity: the gated path was generated

        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        row = check_conn.execute(
            "SELECT updated_at FROM study_progress WHERE id = 'prog-1'"
        ).fetchone()
        check_conn.close()
        source_conn.close()

        assert row[0] == "2024-06-01T00:00:00Z", (
            "destination's newer row must survive the push, not be reverted"
        )

    def test_newer_source_row_does_replace(self, tmp_path):
        """The other half: a genuinely newer source row must still win."""
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        _seed_study_progress(source_conn, "prog-1", updated_at="2024-06-01T00:00:00Z")
        source_conn.commit()

        _seed_session(dest_conn, "sess-1")
        _seed_study_progress(dest_conn, "prog-1", updated_at="2024-01-01T00:00:00Z")
        dest_conn.commit()
        dest_conn.close()

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        row = check_conn.execute(
            "SELECT updated_at FROM study_progress WHERE id = 'prog-1'"
        ).fetchone()
        check_conn.close()
        source_conn.close()

        assert row[0] == "2024-06-01T00:00:00Z", (
            "a genuinely newer source row must still replace the destination's"
        )

    def test_destination_row_absent_still_inserts(self, tmp_path):
        """No conflict yet -> the ON CONFLICT upsert must still behave as a
        plain insert (first-time sync of a global row)."""
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        _seed_study_progress(source_conn, "prog-1", updated_at="2024-06-01T00:00:00Z")
        source_conn.commit()

        _seed_session(dest_conn, "sess-1")
        dest_conn.commit()
        dest_conn.close()

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        count = check_conn.execute(
            "SELECT COUNT(*) FROM study_progress WHERE id = 'prog-1'"
        ).fetchone()[0]
        check_conn.close()
        source_conn.close()

        assert count == 1

    def test_null_destination_updated_at_loses_to_dated_source(self, tmp_path):
        """R-19b (M3 council arbitration A1/A1'): a destination row with a
        NULL updated_at must not freeze forever -- it is "older than
        anything" and any dated source row must win.

        knowledge_bridges.updated_at is nullable (study_progress's is NOT
        NULL, so it cannot construct this case) -- this is exactly the shape
        a pre-R-19 cross-machine sync could have left behind, replicating a
        NULL literally before the recency gate existed.
        """
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        _seed_knowledge_bridge(
            source_conn,
            "bridge-key-1",
            updated_at="2024-06-01 00:00:00",
            quality="effective",
        )
        source_conn.commit()

        _seed_session(dest_conn, "sess-1")
        _seed_knowledge_bridge(
            dest_conn, "bridge-key-1", updated_at=None, quality="proposed"
        )
        dest_conn.commit()
        dest_conn.close()

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        row = check_conn.execute(
            "SELECT quality, updated_at FROM knowledge_bridges WHERE sync_key = 'bridge-key-1'"
        ).fetchone()
        check_conn.close()
        source_conn.close()

        assert row == ("effective", "2024-06-01 00:00:00"), (
            f"a NULL destination updated_at must lose to any dated source row, got {row}"
        )

    def test_null_source_updated_at_does_not_win(self, tmp_path):
        """The other half of R-19b's decision: a NULL *source* updated_at
        must never win, even against a destination that itself has a real
        (older) timestamp -- "no signal" from the incoming row is not
        evidence of freshness.
        """
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        _seed_knowledge_bridge(
            source_conn, "bridge-key-1", updated_at=None, quality="proposed"
        )
        source_conn.commit()

        _seed_session(dest_conn, "sess-1")
        _seed_knowledge_bridge(
            dest_conn,
            "bridge-key-1",
            updated_at="2024-01-01 00:00:00",
            quality="effective",
        )
        dest_conn.commit()
        dest_conn.close()

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        row = check_conn.execute(
            "SELECT quality, updated_at FROM knowledge_bridges WHERE sync_key = 'bridge-key-1'"
        ).fetchone()
        check_conn.close()
        source_conn.close()

        assert row == ("effective", "2024-01-01 00:00:00"), (
            f"a NULL source updated_at must not overwrite a dated destination, got {row}"
        )


class TestStableSyncConflictKeys:
    """R-19e (M3 council, arbitration A5, High): an autoincrement `id` is a
    per-machine counter, not a cross-machine identity. Two machines' row #1s
    silently collide as "the same row" under the old id-keyed upsert --
    reproduced here for `teach_back_scores` (fixed with a migrated-in
    `sync_key`) and `concept_relations` (fixed by using its existing natural
    key, `UNIQUE(source_concept_id, target_concept_id, relation_type)`,
    instead of `id`).
    """

    def _make_migrated_db(
        self, tmp_path: Path, name: str
    ) -> tuple[sqlite3.Connection, Path]:
        return TestRecencyGateEndToEnd()._make_migrated_db(tmp_path, name)

    def test_colliding_autoincrement_id_no_longer_drops_the_incoming_row(
        self, tmp_path
    ):
        """Two machines each write their own teach_back_scores row and both
        happen to be assigned id=1 (the first row on a fresh counter, on
        both). Before R-19e, the upsert conflicted on that shared id and
        silently dropped one of the two rows -- reproduced by the council's
        verifier (row count unchanged, no error). After R-19e, each row has
        its own migration-assigned sync_key, so there is no conflict at all:
        both survive.
        """
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        _seed_session(source_conn, "sess-1")
        source_conn.execute(
            "INSERT INTO teach_back_scores (concept, topic, review_type) "
            "VALUES ('closures', 'python', 'micro')"
        )
        source_conn.commit()
        source_id = source_conn.execute(
            "SELECT id FROM teach_back_scores WHERE concept = 'closures'"
        ).fetchone()[0]

        _seed_session(dest_conn, "sess-1")
        dest_conn.execute(
            "INSERT INTO teach_back_scores (concept, topic, review_type) "
            "VALUES ('decorators', 'python', 'structured')"
        )
        dest_conn.commit()
        dest_id = dest_conn.execute(
            "SELECT id FROM teach_back_scores WHERE concept = 'decorators'"
        ).fetchone()[0]

        # The whole point: both machines' fresh-counter rows landed on the
        # same numeric id, exactly the collision this item closes.
        assert source_id == dest_id == 1

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        concepts = {
            r[0] for r in check_conn.execute("SELECT concept FROM teach_back_scores")
        }
        check_conn.close()
        source_conn.close()

        assert concepts == {"closures", "decorators"}, (
            f"the destination's own row must survive AND the source's must "
            f"arrive -- got {concepts}"
        )

    def test_concept_relations_natural_key_survives_colliding_ids(self, tmp_path):
        """Same collision shape, but concept_relations already has a real
        natural key (UNIQUE(source_concept_id, target_concept_id,
        relation_type)) -- no new column needed, just using it as the
        conflict target instead of the colliding autoincrement id.
        """
        source_conn, source_path = self._make_migrated_db(tmp_path, "source.db")
        dest_conn, dest_path = self._make_migrated_db(tmp_path, "dest.db")

        for conn in (source_conn, dest_conn):
            conn.execute(
                "INSERT INTO concepts (id, name, domain) VALUES ('closures', 'closures', 'python')"
            )
            conn.execute(
                "INSERT INTO concepts (id, name, domain) VALUES ('decorators', 'decorators', 'python')"
            )
            conn.execute(
                "INSERT INTO concepts (id, name, domain) VALUES ('generators', 'generators', 'python')"
            )
            conn.execute(
                "INSERT INTO concepts (id, name, domain) VALUES ('iterators', 'iterators', 'python')"
            )

        _seed_session(source_conn, "sess-1")
        source_conn.execute(
            "INSERT INTO concept_relations "
            "(source_concept_id, target_concept_id, relation_type) "
            "VALUES ('closures', 'decorators', 'prerequisite')"
        )
        source_conn.commit()
        source_id = source_conn.execute(
            "SELECT id FROM concept_relations WHERE source_concept_id = 'closures'"
        ).fetchone()[0]

        _seed_session(dest_conn, "sess-1")
        dest_conn.execute(
            "INSERT INTO concept_relations "
            "(source_concept_id, target_concept_id, relation_type) "
            "VALUES ('generators', 'iterators', 'related_to')"
        )
        dest_conn.commit()
        dest_id = dest_conn.execute(
            "SELECT id FROM concept_relations WHERE source_concept_id = 'generators'"
        ).fetchone()[0]

        assert source_id == dest_id == 1

        sql = _dump_delta_sql(source_path, {"sess-1"})
        assert _stream_sql_to_target(sql, dest_path) is True

        check_conn = sqlite3.connect(dest_path)
        pairs = {
            (r[0], r[1])
            for r in check_conn.execute(
                "SELECT source_concept_id, target_concept_id FROM concept_relations"
            )
        }
        check_conn.close()
        source_conn.close()

        assert pairs == {("closures", "decorators"), ("generators", "iterators")}


class TestBackupDestination:
    """`_backup_destination` is what push/sync call before writing; R-19
    requires it to back up the destination exactly as `pull` already does
    for its own (local) side."""

    def test_local_target_is_backed_up(self, tmp_path):
        _, dest_path = TestRecencyGateEndToEnd()._make_migrated_db(tmp_path, "dest.db")
        backup_dir = tmp_path / "backups"

        with patch(
            "agent_session_tools.maintenance.get_backup_dir",
            return_value=backup_dir,
        ):
            backup_path = _backup_destination(dest_path)

        assert backup_path is not None
        assert Path(backup_path).exists()

    def test_missing_local_target_is_a_noop(self, tmp_path):
        missing = tmp_path / "does-not-exist.db"
        backup_dir = tmp_path / "backups"

        with patch(
            "agent_session_tools.maintenance.get_backup_dir",
            return_value=backup_dir,
        ):
            result = _backup_destination(missing)

        assert result is None

    def test_remote_target_dispatches_to_remote_backup(self, tmp_path):
        """`push`'s destination is always (host, remote_db); prove the
        dispatch reaches the SSH-based remote path rather than trying to
        treat the tuple as a local Path."""
        with patch("agent_session_tools.sync._remote_backup") as mock_remote_backup:
            mock_remote_backup.return_value = "/remote/sessions.db.bak-20240101_000000"
            result = _backup_destination(("host", "/remote/sessions.db"))

        mock_remote_backup.assert_called_once_with("host", "/remote/sessions.db")
        assert result == "/remote/sessions.db.bak-20240101_000000"


class TestPushBacksUpRemoteBeforeWriting:
    """Exercise `push()` itself with SSH mocked, proving the backup call
    happens before the write, not just that the helper exists."""

    def test_push_calls_backup_before_streaming(self, tmp_path, monkeypatch):
        import agent_session_tools.sync as sync_mod

        conn, local_db = TestRecencyGateEndToEnd()._make_migrated_db(
            tmp_path, "local.db"
        )
        _seed_session(conn, "sess-1")
        conn.commit()
        conn.close()

        call_order: list[str] = []

        monkeypatch.setattr(
            sync_mod, "_resolve_remote", lambda remote, tier="hot": ("host", "/r.db")
        )
        monkeypatch.setattr(sync_mod, "_remote_db_exists", lambda host, db: True)
        monkeypatch.setattr(
            sync_mod,
            "_get_sync_state",
            lambda *a, **k: ({"sess-1"}, set()),
        )
        monkeypatch.setattr(
            sync_mod,
            "_backup_destination",
            lambda target: call_order.append("backup"),
        )
        monkeypatch.setattr(
            sync_mod,
            "_stream_sql_to_target",
            lambda sql, target: call_order.append("stream") or True,
        )

        sync_mod.push(remote="host:/r.db", db=local_db, tier="hot")

        assert call_order == ["backup", "stream"]
