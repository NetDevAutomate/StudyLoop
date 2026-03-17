"""Database health checks for review DB and sessions DB."""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import TYPE_CHECKING

from studyctl.doctor.models import CheckResult

if TYPE_CHECKING:
    from pathlib import Path


def _get_review_db_path() -> Path:
    from studyctl.settings import get_db_path

    return get_db_path()


def _get_sessions_db_path() -> Path:
    """Discover sessions DB path from agent-session-tools without hard import."""
    try:
        from agent_session_tools.config import get_db_path  # type: ignore[import-untyped]

        return get_db_path()
    except Exception:
        from studyctl.settings import CONFIG_DIR

        return CONFIG_DIR / "sessions.db"


def check_review_db() -> list[CheckResult]:
    db_path = _get_review_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "database",
                "review_db",
                "warn",
                f"Review DB not found: {db_path}",
                "studyctl review will create it on first use",
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
                    "studyctl review --rebuild",
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
                "uv pip install agent-session-tools",
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
        conn.close()
        return [
            CheckResult(
                "database",
                "sessions_db",
                "pass",
                f"Sessions DB healthy: {db_path}",
                "",
                fix_auto=False,
            )
        ]
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
