"""Focus topics — the user's current (max 3) active study areas.

Focus is an *attention filter*, not a data-retention concept: it shapes what
``studyloop now`` / ``review`` recommend and what session suggestions lead
with. It never deletes anything (disk management is ``prune``'s job, and
prune is age-based, not topic-based).

The 3-topic ceiling reuses ``MAX_ACTIVE_TOPICS`` — the same overload guard
applied to review sessions. More than three parallel topics fragments
attention and stalls spaced-repetition progress.

Stored in config.yaml::

    focus:
      topics: [python, sql]
      updated: "2026-07-26"
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from studyloop.settings import (
    MAX_ACTIVE_TOPICS,
    load_raw_config,
    write_raw_config,
)

if TYPE_CHECKING:
    from pathlib import Path

STALE_AFTER_DAYS = 30


@dataclass
class FocusState:
    """Current focus topics and when they were last confirmed."""

    topics: list[str] = field(default_factory=list)
    updated: str | None = None

    @property
    def is_set(self) -> bool:
        return bool(self.topics)

    @property
    def is_stale(self) -> bool:
        """True when focus was last confirmed more than STALE_AFTER_DAYS ago."""
        if not self.updated:
            return self.is_set  # topics without a date: treat as stale
        try:
            updated = date.fromisoformat(self.updated)
        except ValueError:
            return True
        return (date.today() - updated).days > STALE_AFTER_DAYS


def get_focus() -> FocusState:
    """Read the focus section from config.yaml."""
    raw = load_raw_config()
    section = raw.get("focus") or {}
    topics = section.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    return FocusState(
        topics=[str(t).strip() for t in topics if str(t).strip()][:MAX_ACTIVE_TOPICS],
        updated=str(section["updated"]) if section.get("updated") else None,
    )


def set_focus(topics: list[str]) -> Path:
    """Persist up to MAX_ACTIVE_TOPICS focus topics. Raises ValueError beyond."""
    cleaned: list[str] = []
    for topic in topics:
        name = str(topic).strip()
        if name and name.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(name)
    if not cleaned:
        raise ValueError("At least one focus topic is required.")
    if len(cleaned) > MAX_ACTIVE_TOPICS:
        raise ValueError(
            f"Maximum {MAX_ACTIVE_TOPICS} focus topics — pick the ones that "
            "matter most right now. Fewer active topics means faster progress."
        )
    raw = load_raw_config()
    raw["focus"] = {"topics": cleaned, "updated": date.today().isoformat()}
    return write_raw_config(raw)


def clear_focus() -> Path:
    """Remove the focus section entirely."""
    raw = load_raw_config()
    raw.pop("focus", None)
    return write_raw_config(raw)


def matches_focus(topic: str, focus_topics: list[str]) -> bool:
    """Loose topic match: case-insensitive substring in either direction."""
    candidate = topic.strip().lower()
    if not candidate:
        return False
    for focus_topic in focus_topics:
        f = focus_topic.strip().lower()
        if f and (f in candidate or candidate in f):
            return True
    return False


def suggest_focus(days: int = 30, limit: int = 6) -> list[tuple[str, str]]:
    """Suggest focus candidates as ``(topic, evidence)`` pairs.

    Sources, in priority order:
    1. Recent study-session topics (what the user actually studied)
    2. Topics with struggling/learning concepts (active repair targets)
    3. Configured course topics (declared intent)
    """
    suggestions: dict[str, str] = {}
    # R-20: study_sessions.started_at is written via SQLite's own
    # datetime('now') ("YYYY-MM-DD HH:MM:SS", UTC, no offset suffix) --
    # match that format exactly (strftime, not isoformat) so the string
    # comparison below stays correct, and derive it from real UTC rather
    # than the naive local wall clock, which shifted this window by the
    # machine's UTC offset.
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    conn = _connect_sessions_db()
    if conn is not None:
        try:
            try:
                rows = conn.execute(
                    """
                    SELECT topic, COUNT(*) AS n FROM study_sessions
                    WHERE started_at >= ? AND topic IS NOT NULL AND topic != ''
                    GROUP BY LOWER(topic) ORDER BY n DESC LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
                for row in rows:
                    suggestions.setdefault(
                        str(row[0]),
                        f"{row[1]} study session(s) in the last {days} days",
                    )
            except sqlite3.OperationalError:
                pass
            try:
                rows = conn.execute(
                    """
                    SELECT topic, COUNT(*) AS n FROM study_progress
                    WHERE confidence IN ('struggling', 'learning')
                      AND topic IS NOT NULL AND topic != ''
                    GROUP BY LOWER(topic) ORDER BY n DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                for row in rows:
                    suggestions.setdefault(str(row[0]), f"{row[1]} concept(s) still in progress")
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

    try:
        from studyloop.topics import get_topics

        for topic in get_topics():
            suggestions.setdefault(topic.name, "configured course topic")
    except Exception:
        pass

    return list(suggestions.items())[:limit]


def _connect_sessions_db() -> sqlite3.Connection | None:
    """Read-only connection to the sessions DB, best-effort."""
    try:
        from studyloop.settings import CONFIG_DIR

        db = CONFIG_DIR / "sessions.db"
        try:
            from agent_session_tools.config_loader import get_db_path

            db = get_db_path()
        except ImportError:
            pass
        if not db.exists():
            return None
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception:
        return None
