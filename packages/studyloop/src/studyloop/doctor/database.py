"""Database health checks for review DB and sessions DB."""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import TYPE_CHECKING

from studyloop.doctor.models import CheckResult

if TYPE_CHECKING:
    from pathlib import Path


def _get_review_db_path() -> Path:
    from studyloop.settings import get_db_path

    return get_db_path()


def _get_sessions_db_path() -> Path:
    """Resolve the sessions DB path the same way the rest of the app does.

    Previously this tried ``agent_session_tools.config``, a module that no
    longer exists (it was renamed to ``config_loader``), and fell back to a
    hardcoded ``CONFIG_DIR / "sessions.db"`` on the resulting ImportError. The
    fallback therefore ran *every* time, so ``studyloop doctor`` reported on
    the default database even when ``session_db`` pointed somewhere else —
    a silently wrong health check.

    ``studyloop.settings.get_db_path`` is the single resolver that honours the
    ``session_db`` / ``database.path`` config keys, then ``STUDYLOOP_DB``, then
    the default.
    """
    from studyloop.settings import get_db_path

    return get_db_path()


def check_review_db() -> list[CheckResult]:
    db_path = _get_review_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "database",
                "review_db",
                "warn",
                f"Review DB not found: {db_path}",
                "studyloop review will create it on first use",
                fix_auto=False,
            )
        ]
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA integrity_check")
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        expected = {"card_reviews", "review_sessions"}
        missing = expected - tables
        if missing:
            return [
                CheckResult(
                    "database",
                    "review_db",
                    "fail",
                    f"Review DB missing tables: {', '.join(sorted(missing))}",
                    "studyloop review --rebuild",
                    fix_auto=True,
                )
            ]
        return [
            CheckResult(
                "database",
                "review_db",
                "pass",
                f"Review DB healthy: {db_path}",
                "",
                fix_auto=False,
            )
        ]
    except sqlite3.DatabaseError as exc:
        return [
            CheckResult(
                "database",
                "review_db",
                "fail",
                f"Review DB corrupt: {exc}",
                f"Delete and recreate: rm {db_path}",
                fix_auto=False,
            )
        ]


def check_sessions_db() -> list[CheckResult]:
    spec = importlib.util.find_spec("agent_session_tools")
    if spec is None:
        return [
            CheckResult(
                "database",
                "sessions_db",
                "info",
                "agent-session-tools not installed — sessions DB not checked",
                "studyloop install tools",
                fix_auto=False,
            )
        ]
    db_path = _get_sessions_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "database",
                "sessions_db",
                "warn",
                f"Sessions DB not found: {db_path}",
                "Run any agent session tool to create it",
                fix_auto=False,
            )
        ]
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA integrity_check")
        results = [
            CheckResult(
                "database",
                "sessions_db",
                "pass",
                f"Sessions DB healthy: {db_path}",
                "",
                fix_auto=False,
            )
        ]
        results.extend(_check_fts_drift(conn, db_path))
        conn.close()
        return results
    except sqlite3.DatabaseError as exc:
        return [
            CheckResult(
                "database",
                "sessions_db",
                "fail",
                f"Sessions DB corrupt: {exc}",
                f"Delete and recreate: rm {db_path}",
                fix_auto=False,
            )
        ]


def _check_fts_drift(conn: sqlite3.Connection, db_path: Path) -> list[CheckResult]:
    """Check the FTS invariant: index rows == messages with content.

    A drifting index is the failure mode that once grew a sessions DB to
    45GB (the same 32MB of messages indexed ~586 times by a non-idempotent
    export path). Catch it the day it starts, on every machine.
    """
    try:
        messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE content IS NOT NULL"
        ).fetchone()[0]
        fts_rows = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    except sqlite3.OperationalError:
        # Tables not created yet (fresh DB) — nothing to check.
        return []

    drift = fts_rows - messages
    if drift == 0:
        return [
            CheckResult(
                "database",
                "sessions_fts",
                "pass",
                f"FTS index consistent ({fts_rows:,} rows)",
                "",
                fix_auto=False,
            )
        ]
    # Any drift is an invariant violation; large drift means the index is
    # being duplicated and the DB will bloat without bound.
    severity = "fail" if abs(drift) > max(100, messages // 10) else "warn"
    return [
        CheckResult(
            "database",
            "sessions_fts",
            severity,
            f"FTS index drift: {fts_rows:,} index rows for {messages:,} messages ({drift:+,})",
            "session-maint fts-check --fix",
            # Auto-fixable: `doctor --fix` calls tiering.repair_fts() directly.
            # This was False while the remedy string was still shown, so
            # `doctor --fix` printed the repair command and never ran it.
            fix_auto=True,
        )
    ]
