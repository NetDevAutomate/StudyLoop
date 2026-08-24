"""`studyloop doctor --fix` must actually repair FTS index drift.

Regression test for a specific class of dishonesty: the check reported the drift
AND printed `session-maint fts-check --fix` as the remedy, but carried
``fix_auto=False`` and had no branch in ``_apply_fixes``. So `doctor --fix` ran,
said nothing, exited, and left a 916,306-row drift in place — while appearing to
have offered and applied a fix.

The invariant under test is countable: after `--fix`, index rows == messages with
content, exactly. Not "smaller". Zero drift.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _build_drifted_db(path: Path, *, messages: int, duplication: int) -> None:
    """Create a sessions DB whose FTS index holds `duplication`x the real rows.

    Mirrors the real failure: a non-idempotent export path re-indexed the same
    messages repeatedly, so the FTS table is a multiple of the message count
    rather than corrupt in any way SQLite would report.
    """
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "CREATE TABLE messages ("
            "  id INTEGER PRIMARY KEY,"
            "  session_id TEXT,"
            "  role TEXT,"
            "  content TEXT"
            ")"
        )
        # Canonical DDL, copied from agent_session_tools.migrations — repair_fts
        # inserts (rowid, content, session_id, role), so a simpler fts5(content)
        # fixture would fail on a missing column and prove nothing about drift.
        conn.execute(
            "CREATE VIRTUAL TABLE messages_fts USING fts5("
            "  content,"
            "  session_id UNINDEXED,"
            "  role UNINDEXED,"
            "  tokenize='porter unicode61'"
            ")"
        )
        for i in range(messages):
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (f"s{i % 3}", "user", f"message body {i}"),
            )
        # Index each message `duplication` times to manufacture the drift.
        for _ in range(duplication):
            conn.execute(
                "INSERT INTO messages_fts (content, session_id, role) "
                "SELECT content, session_id, role FROM messages"
            )
    conn.close()


@pytest.fixture
def drifted_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "sessions.db"
    _build_drifted_db(db, messages=40, duplication=5)
    # _get_sessions_db_path() resolves via studyloop.settings.get_db_path, which
    # honours STUDYLOOP_DB — so this points every doctor path at the temp DB.
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    return db


def _counts(db: Path) -> tuple[int, int]:
    conn = sqlite3.connect(db)
    try:
        messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE content IS NOT NULL"
        ).fetchone()[0]
        fts_rows = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    finally:
        conn.close()
    return messages, fts_rows


class TestFtsDriftIsDetected:
    def test_drift_is_reported_as_auto_fixable(self, drifted_db: Path) -> None:
        """A drift the tool can repair itself must not be reported as manual-only.

        `fix_auto=False` is what made `--fix` skip it, so this assertion is the
        one that actually guards the bug.
        """
        from studyloop.doctor.database import check_sessions_db

        results = check_sessions_db()
        fts = [r for r in results if r.name == "sessions_fts"]
        assert fts, f"no sessions_fts result among {[r.name for r in results]}"
        assert fts[0].status in ("warn", "fail"), f"drift not flagged: {fts[0].message}"
        assert fts[0].fix_auto is True, "drift is repairable in-process but marked manual-only"


class TestDoctorFixRepairsDrift:
    def test_apply_fixes_drives_drift_to_exactly_zero(self, drifted_db: Path) -> None:
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.database import check_sessions_db

        messages_before, fts_before = _counts(drifted_db)
        assert fts_before == messages_before * 5, "fixture did not create the expected drift"

        actions = _apply_fixes(check_sessions_db())

        messages_after, fts_after = _counts(drifted_db)
        assert fts_after == messages_after, (
            f"drift survived --fix: {fts_after} index rows for {messages_after} messages"
        )
        assert messages_after == messages_before, "repair must not touch the source of truth"
        assert any("FTS" in a or "fts" in a for a in actions), (
            f"repair happened silently — no action reported: {actions}"
        )

    def test_second_fix_is_idempotent(self, drifted_db: Path) -> None:
        """Running --fix twice must not re-duplicate what it just repaired."""
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.database import check_sessions_db

        _apply_fixes(check_sessions_db())
        messages, fts = _counts(drifted_db)
        assert fts == messages

        # Second pass: the check should now be clean, so no fix should run.
        _apply_fixes(check_sessions_db())
        messages_again, fts_again = _counts(drifted_db)
        assert fts_again == messages_again == messages
