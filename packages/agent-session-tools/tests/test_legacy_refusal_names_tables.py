"""The legacy-sync refusal names the table(s) that triggered it.

``replication.legacy.check_database`` refuses a legacy SQL copy when any row exists
in a protected ``context_*`` table. Until now the message was the same fixed text
whatever the cause, so a learner shown "Legacy SQL sync cannot transfer scoped or
source-grounded memory" could not tell whether the trigger was captured evidence
(every current-schema export writes ``context_evidence``), a deletion marker, or a
parked-topic board layout (remediation plan 5, lane Q, item B). The protected set
itself is unchanged: read-and-prove showed every exported database carries
``context_evidence`` rows that ``tiering.sync_to_full`` would drop, so no narrowing
of the set would make the legacy copier correct for a real database. (Remediation
plan 6 replaced that copier with the registry mirror; ``sync_to_full`` no longer
consults this guard, and the set still protects every legacy and peer path.)
"""

from __future__ import annotations

import sqlite3

import pytest

from agent_session_tools import tiering
from agent_session_tools.export_sessions import init_db
from agent_session_tools.replication import legacy


def _open(path):
    conn = init_db(str(path))
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
        "VALUES ('s0', 'claude_code', '2026-01-01', '2026-01-01', 'h0')"
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp) "
        "VALUES ('s0-m0', 's0', 'user', 'hello decorators', '2026-01-01')"
    )
    conn.commit()
    return conn


class TestRefusalNamesTheOffendingTables:
    def test_one_protected_table_is_named(self, tmp_path):
        conn = _open(tmp_path / "hot.db")
        conn.execute(
            "INSERT INTO context_projects VALUES ('p','personal','fixture','fixture')"
        )
        conn.commit()

        with pytest.raises(legacy.LegacySyncRefused) as excinfo:
            legacy.check_database(conn)

        text = str(excinfo.value)
        assert text.startswith(legacy.MESSAGE), text
        assert "context_projects" in text
        # A single offender is named alone; nothing else is blamed.
        assert "context_tombstones" not in text and "context_evidence" not in text

    def test_every_offending_table_is_named_sorted(self, tmp_path):
        conn = _open(tmp_path / "hot.db")
        conn.execute(
            "INSERT INTO context_tombstones VALUES ('gone','deletion','fixture')"
        )
        conn.execute(
            "INSERT INTO context_board_columns VALUES ('unclassified','todo','To do',0)"
        )
        conn.commit()

        with pytest.raises(legacy.LegacySyncRefused) as excinfo:
            legacy.check_database(conn)

        text = str(excinfo.value)
        assert text.startswith(legacy.MESSAGE), text
        # The tombstone insert also fires the retirement trigger; all three are named.
        tail = text[len(legacy.MESSAGE) :]
        assert (
            tail.index("context_board_columns")
            < tail.index("context_retirements")
            < tail.index("context_tombstones")
        ), tail

    def test_attached_schema_is_named_with_its_table(self, tmp_path):
        """``sync_to_full`` checks the hot DB through an ATTACH; the name must still read."""
        hot = tmp_path / "hot.db"
        conn = _open(hot)
        conn.execute(
            "INSERT INTO context_projects VALUES ('p','personal','fixture','fixture')"
        )
        conn.commit()
        conn.close()
        other = init_db(str(tmp_path / "full.db"))
        other.execute("ATTACH DATABASE ? AS hot", (str(hot),))

        with pytest.raises(legacy.LegacySyncRefused, match="context_projects"):
            legacy.check_database(other, "hot")

    def test_conditional_tables_are_named_only_when_their_condition_holds(
        self, tmp_path
    ):
        """``context_policy_state``/``context_lifecycle_mode`` rows exist on every
        migrated DB; only an applied policy or a non-ordinary mode is protected."""
        conn = _open(tmp_path / "hot.db")
        legacy.check_database(conn)  # the fresh singletons alone never refuse
        conn.execute("UPDATE context_lifecycle_mode SET mode='evict' WHERE id=1")
        conn.commit()

        with pytest.raises(legacy.LegacySyncRefused) as excinfo:
            legacy.check_database(conn)

        text = str(excinfo.value)
        assert "context_lifecycle_mode" in text
        assert "context_policy_state" not in text

    def test_sync_full_mirrors_what_the_legacy_guard_protects(
        self, tmp_path, monkeypatch
    ):
        """Pin reversed by remediation plan 6 (lane T, T4): ``sync_to_full`` is no
        longer a legacy copier. It mirrors the context tier into a bound full
        database, so the evidence the guard names arrives instead of refusing;
        the guard itself still refuses that database for every legacy/peer path."""
        hot = tmp_path / "sessions.db"
        full_dir = tmp_path / "external"
        full_dir.mkdir()
        full = full_dir / "sessions_full.db"
        config = tmp_path / "config.yaml"
        config.write_text(
            f"database:\n  path: {hot}\n  backup_dir: {full_dir}\n  full_db_path: {full}\n"
        )
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
        conn = _open(hot)
        conn.execute(
            "INSERT INTO context_evidence VALUES ('e','k','s0','claude_code','jsonl',"
            "'/x','v1','m',NULL,'2026-01-01','body','sha','conversation_message',"
            "NULL,NULL,NULL,NULL)"
        )
        conn.commit()
        with pytest.raises(legacy.LegacySyncRefused, match="context_evidence"):
            legacy.check_database(conn)
        conn.close()

        tiering.sync_to_full()

        archive = sqlite3.connect(full)
        assert archive.execute("SELECT id FROM context_evidence").fetchall() == [("e",)]
        with pytest.raises(legacy.LegacySyncRefused, match="context_evidence"):
            legacy.check_database(archive)
        archive.close()


class TestProtectedSetUnchanged:
    """The set itself is not narrowed (lane Q read-and-prove, plan 5 item B)."""

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO context_tombstones VALUES ('gone','deletion','fixture')",
            "INSERT INTO context_board_columns VALUES ('unclassified','todo','To do',0)",
            "INSERT INTO context_projects VALUES ('p','personal','fixture','fixture')",
        ],
    )
    def test_a_row_in_a_protected_table_still_refuses(self, tmp_path, statement):
        conn = _open(tmp_path / "hot.db")
        conn.execute(statement)
        conn.commit()
        with pytest.raises(legacy.LegacySyncRefused, match="Legacy SQL sync"):
            legacy.check_database(conn)

    def test_protected_queries_still_yield_plain_sql(self, tmp_path):
        """``sync.py`` and ``transaction_guard`` consume the queries as SQL strings."""
        conn = _open(tmp_path / "hot.db")
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        queries = list(legacy.protected_queries(tables))
        assert queries and all(
            isinstance(q, str) and q.startswith("SELECT 1 FROM ") for q in queries
        )
        assert all(conn.execute(q).fetchone() is None for q in queries)
