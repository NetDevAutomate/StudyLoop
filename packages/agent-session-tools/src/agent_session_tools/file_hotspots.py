"""File hotspot analysis — which files are most referenced across sessions."""

from __future__ import annotations

import sqlite3


def get_hotspots(
    conn: sqlite3.Connection,
    project: str | None = None,
    since_days: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return file access frequency ranked by reference count.

    Args:
        conn: Database connection
        project: Project key as stored in sessions.project_path (pre-encoded)
        since_days: Only count references from the last N days
        limit: Maximum files to return
    """
    conditions = []
    params: list = []

    if project:
        conditions.append("s.project_path = ?")
        params.append(project)

    if since_days:
        conditions.append("fr.timestamp >= datetime('now', ?)")
        params.append(f"-{since_days} days")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT fr.file_path,
               COUNT(*) as ref_count,
               COUNT(DISTINCT fr.session_id) as session_count,
               MAX(fr.timestamp) as last_seen
        FROM file_references fr
        JOIN sessions s ON fr.session_id = s.id
        {where}
        GROUP BY fr.file_path
        ORDER BY ref_count DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [
        {
            "file_path": row[0],
            "ref_count": row[1],
            "session_count": row[2],
            "last_seen": row[3],
        }
        for row in rows
    ]
