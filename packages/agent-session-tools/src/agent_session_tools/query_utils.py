"""Utility functions for session querying — date parsing, FTS escaping, DB helpers."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def get_db_size(db_path: Path) -> dict:
    """Get database file size and formatted string."""
    if not db_path.exists():
        return {"bytes": 0, "mb": 0, "formatted": "0 B"}

    size_bytes = db_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    # Format for display
    if size_mb < 1:
        formatted = f"{size_bytes / 1024:.2f} KB"
    elif size_mb < 1024:
        formatted = f"{size_mb:.2f} MB"
    else:
        formatted = f"{size_mb / 1024:.2f} GB"

    return {"bytes": size_bytes, "mb": size_mb, "formatted": formatted}


def check_thresholds(size_mb: float, config: dict) -> dict:
    """Check if database size exceeds thresholds."""
    thresholds = config.get("thresholds", {})
    warning_mb = thresholds.get("warning_mb", 100)
    critical_mb = thresholds.get("critical_mb", 500)

    result: dict = {
        "status": "ok",
        "message": None,
        "warning_mb": warning_mb,
        "critical_mb": critical_mb,
    }

    if size_mb >= critical_mb:
        result["status"] = "critical"
        result["message"] = (
            f"Database size ({size_mb:.2f} MB) exceeds critical threshold ({critical_mb} MB)"
        )
        logger.critical(result["message"])
    elif size_mb >= warning_mb:
        result["status"] = "warning"
        result["message"] = (
            f"Database size ({size_mb:.2f} MB) exceeds warning threshold ({warning_mb} MB)"
        )
        logger.warning(result["message"])
    else:
        result["message"] = (
            f"Database size ({size_mb:.2f} MB) is within acceptable limits"
        )

    return result


def parse_date(date_str: str) -> str:
    """Parse date string to ISO format for SQL queries.

    Supports:
    - ISO format: '2024-01-01' -> '2024-01-01T00:00:00'
    - Relative: 'last-week', 'last-month', 'last-90-days'
    """
    date_str = date_str.lower().strip()

    # Relative dates
    if date_str.startswith("last-"):
        days_map = {
            "last-day": 1,
            "last-week": 7,
            "last-month": 30,
            "last-90-days": 90,
            "last-year": 365,
        }

        if date_str in days_map:
            target_date = datetime.now() - timedelta(days=days_map[date_str])
            return target_date.isoformat()

        # Try parsing 'last-N-days'
        if date_str.startswith("last-") and date_str.endswith("-days"):
            try:
                days = int(date_str[5:-5])  # Extract N from 'last-N-days'
                target_date = datetime.now() - timedelta(days=days)
                return target_date.isoformat()
            except ValueError:
                pass

    # ISO date format (YYYY-MM-DD)
    try:
        parsed = datetime.fromisoformat(date_str)
        return parsed.isoformat()
    except ValueError:
        pass

    # Try parsing as date only
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.isoformat()
    except ValueError as err:
        raise ValueError(
            f"Invalid date format: {date_str}. "
            "Use YYYY-MM-DD or last-week/last-month/last-N-days"
        ) from err


def build_date_filter(
    since: str | None = None, before: str | None = None
) -> tuple[str, list]:
    """Build SQL WHERE clause for date filtering.

    Returns: (where_clause, params)
    """
    conditions = []
    params: list[str] = []

    if since:
        since_iso = parse_date(since)
        conditions.append("updated_at >= ?")
        params.append(since_iso)

    if before:
        before_iso = parse_date(before)
        conditions.append("updated_at <= ?")
        params.append(before_iso)

    where_clause = " AND ".join(conditions) if conditions else ""
    return where_clause, params


def escape_fts_query(query: str) -> str:
    """Escape a query string for FTS5 MATCH.

    With porter stemming enabled, we can use simpler queries that match variants.
    Wraps the query in double quotes for phrase search when needed, but allows
    simple word queries to benefit from stemming.
    """
    # Remove any existing quotes
    query = query.strip().strip('"').strip("'")

    # If query contains FTS operators (AND, OR, NOT), use as-is
    if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
        return query

    # For simple queries, escape quotes and use as phrase if multi-word
    escaped = query.replace('"', '""')

    # Multi-word queries become phrases
    if " " in escaped:
        return f'"{escaped}"'

    # Single words benefit from stemming without quotes
    return escaped


def resolve_session_id(conn: sqlite3.Connection, user_input: str) -> str:
    """Resolve partial session ID to full ID safely.

    Args:
        conn: Database connection
        user_input: User-provided session ID (partial or full)

    Returns:
        Full session ID

    Raises:
        ValueError: If session not found or ambiguous
    """
    # Try exact match first (fastest)
    exact = conn.execute(
        "SELECT id FROM sessions WHERE id = ?", (user_input,)
    ).fetchone()
    if exact:
        return exact[0]

    # Try prefix match
    matches = conn.execute(
        "SELECT id, source, project_path FROM sessions WHERE id LIKE ? LIMIT 10",
        (f"{user_input}%",),
    ).fetchall()

    if len(matches) == 0:
        raise ValueError(f"No sessions found matching: {user_input}")
    elif len(matches) == 1:
        return matches[0][0]
    else:
        # Multiple matches - show disambiguation
        error_msg = [f"Multiple sessions match '{user_input}':"]
        for i, (session_id, source, project) in enumerate(matches[:5], 1):
            project_short = (project or "Unknown")[:50]
            error_msg.append(f"  {i}. [{source}] {session_id} | {project_short}")

        if len(matches) > 5:
            error_msg.append(f"  ... and {len(matches) - 5} more")

        error_msg.append("\nUse more characters or the full session ID.")
        raise ValueError("\n".join(error_msg))
