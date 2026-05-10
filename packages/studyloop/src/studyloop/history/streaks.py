"""Study streak calculation from session history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from . import _connection


def get_study_streaks() -> dict:
    """Calculate study streak data from session history.

    Returns {current_streak, longest_streak, total_days, sessions_this_week,
             last_session_date, day_counts}.
    """
    conn = _connection._connect()
    empty = {
        "current_streak": 0,
        "longest_streak": 0,
        "total_days": 0,
        "sessions_this_week": 0,
        "last_session_date": None,
    }
    if not conn:
        return empty
    try:
        # Get distinct study days (dates only) from last 90 days
        rows = conn.execute(
            """
            SELECT DISTINCT DATE(COALESCE(s.updated_at, s.created_at)) as study_date
            FROM sessions s
            WHERE s.created_at > datetime('now', '-90 days')
            ORDER BY study_date DESC
            """
        ).fetchall()

        if not rows:
            return empty

        study_dates = [datetime.fromisoformat(r["study_date"]).date() for r in rows]
        today = datetime.now(UTC).date()

        # Calculate current streak (consecutive days ending today or yesterday)
        current_streak = 0
        check_date = today
        for d in study_dates:
            if d == check_date or d == check_date - timedelta(days=1):
                current_streak += 1
                check_date = d - timedelta(days=1)
            else:
                break

        # Calculate longest streak
        longest_streak = 1
        current_run = 1
        sorted_dates = sorted(study_dates)
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                current_run += 1
                longest_streak = max(longest_streak, current_run)
            else:
                current_run = 1

        # Sessions this week
        week_start = today - timedelta(days=today.weekday())
        sessions_this_week = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM sessions
            WHERE DATE(COALESCE(updated_at, created_at)) >= ?
            """,
            (week_start.isoformat(),),
        ).fetchone()["cnt"]

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_days": len(study_dates),
            "sessions_this_week": sessions_this_week,
            "last_session_date": study_dates[0].isoformat() if study_dates else None,
        }
    except sqlite3.OperationalError:
        return empty
    finally:
        conn.close()
