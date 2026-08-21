"""Parking lot persistence — store and manage tangential topics for future sessions.

During a study session, the AI agent parks tangential questions here.
At session start, unresolved parked topics are surfaced via ``studyloop resume``.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from studyloop.db import SCHEMA_LOCK, connect_db
from studyloop.markdown_notes import normalise_markdown
from studyloop.settings import get_db_path

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

#: The board's out-of-the-box columns, seeded on first read of a fresh (or
#: freshly-healed) database. Ordered left-to-right as they appear on the board.
_DEFAULT_BOARD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("inbox", "Inbox"),
    ("next", "Next"),
    ("exploring", "Exploring"),
    ("done", "Done"),
)

#: Fields a caller may edit in place via :func:`update_parked_topic`. Anything
#: outside this set is rejected loudly (a typo'd/forbidden field must not
#: silently no-op) — mirrors :data:`studyloop.notes._EDITABLE`.
_EDITABLE_TOPIC_FIELDS: frozenset[str] = frozenset(
    {"question", "notes", "tech_area", "context", "priority", "board_column"}
)


def _connect() -> sqlite3.Connection:
    """Get a connection to the session DB with WAL mode and busy timeout.

    Ensures the parked_topics table is present and up to date:
    1. Always run migrations (idempotent — skips already-applied versions)
    2. If that fails (version/schema drift), create the table directly

    The fallback handles a real-world failure mode: PRAGMA user_version
    can advance past the actual schema state if a migration partially
    succeeds. When that happens, the migration system skips the CREATE
    TABLE (thinks it already ran) and later migrations fail because the
    table doesn't exist. The direct CREATE is self-healing for this case.
    """
    conn = connect_db(get_db_path(), row_factory=True)

    # Serialise the check-and-create schema repair across threads. Uvicorn
    # serves sync endpoints on a threadpool, so two concurrent first-readers
    # can reach the self-healing CREATE/ALTER path together; one would win and
    # the other raise "table/column already exists". Holding SCHEMA_LOCK across
    # the whole repair makes it idempotent between threads (see db.SCHEMA_LOCK).
    with SCHEMA_LOCK:
        # Base schema first. parked_topics has FKs to sessions(id) and
        # study_sessions(id); on a database whose first writer is the parking
        # board neither table exists yet, so every INSERT fails with
        # "no such table: main.sessions" under PRAGMA foreign_keys=ON. Only the
        # export pipeline created them, so opening the board before ever running
        # session-export was fatal.
        #
        # init_db applies the canonical schema.sql and runs migrations, so the
        # base DDL is not duplicated here. Reconnect afterwards because it
        # returns its own connection.
        try:
            conn.execute("SELECT 1 FROM sessions LIMIT 0")
        except sqlite3.OperationalError:
            logger.info("Initialising base session schema for parked_topics")
            conn.close()
            try:
                from agent_session_tools.export_sessions import init_db

                init_db(str(get_db_path())).close()
            except Exception:
                logger.warning("Base schema init failed for parked_topics", exc_info=True)
            conn = connect_db(get_db_path(), row_factory=True)

        # Always run migrations — they're idempotent (check user_version)
        # and handle both missing tables AND missing columns from newer versions.
        try:
            from agent_session_tools.migrations import migrate

            migrate(conn)
        except Exception:
            pass

        # If migrations didn't create the table, create it directly (self-healing)
        try:
            conn.execute("SELECT 1 FROM parked_topics LIMIT 0")
        except sqlite3.OperationalError:
            logger.info("Creating parked_topics table directly (migration drift recovery)")
            _create_parked_topics_table(conn)

        # Board columns (notes/board_column/board_order/updated_at + the
        # board_columns table) are NOT created by any migration, so a drifted
        # DB would hit "no such column: board_column" on its first board load.
        # Heal them here every connect — cheap and idempotent.
        _ensure_board_schema(conn)

    return conn


@contextmanager
def _immediate(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a read-modify-write inside a single ``BEGIN IMMEDIATE`` transaction.

    Python's :mod:`sqlite3` defers its implicit ``BEGIN`` until the first DML
    statement, so a ``SELECT`` that feeds a later ``INSERT``/``UPDATE`` runs
    without holding the write lock. Two callers can then read the same state
    and write conflicting values — a lost update (e.g. two cards appended to a
    column both reading the same ``MAX(board_order)`` and landing on the same
    order). ``BEGIN IMMEDIATE`` takes the write lock up front, so concurrent
    writers serialise (they wait out ``busy_timeout``) instead of racing.

    Switches the connection to manual-commit for the duration and restores its
    prior ``isolation_level`` afterwards.
    """
    prior = conn.isolation_level
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    finally:
        conn.isolation_level = prior


def _create_parked_topics_table(conn: sqlite3.Connection) -> None:
    """Create parked_topics with the full current schema.

    This is a last-resort fallback when the migration system can't
    self-heal. The schema matches the cumulative result of v14-v17, v26:
    - v14: base table
    - v15: unique index (session_id, question)
    - v16: source, tech_area columns; index updated to include source
    - v17: priority column
    - v26: park_count column; partial unique index on (question, source)
           WHERE status = 'pending' (replaces old session-scoped index)

    Uses IF NOT EXISTS / IF NOT EXISTS throughout so it's safe to call
    repeatedly — idempotency means no harm if the table already exists.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            topic_tag TEXT,
            question TEXT NOT NULL,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
            scheduled_for TEXT,
            resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT 'parked',
            tech_area TEXT,
            priority INTEGER,
            park_count INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_parked_topics_question_source_pending
        ON parked_topics (question, source) WHERE status = 'pending'
    """)
    conn.commit()


def _ensure_board_schema(conn: sqlite3.Connection) -> None:
    """Add the Kanban-board columns and metadata table, seeding defaults.

    Idempotent and self-healing: adds ``notes``/``board_column``/``board_order``/
    ``updated_at`` to ``parked_topics`` only when absent (SQLite has no
    ``ADD COLUMN IF NOT EXISTS``, so we inspect ``PRAGMA table_info`` first),
    creates the ``board_columns`` table, and seeds the default columns on an
    empty board. Caller must already hold :data:`SCHEMA_LOCK`.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(parked_topics)")}
    additions = {
        "notes": "ALTER TABLE parked_topics ADD COLUMN notes TEXT",
        "board_column": "ALTER TABLE parked_topics ADD COLUMN board_column TEXT",
        "board_order": "ALTER TABLE parked_topics ADD COLUMN board_order INTEGER",
        "updated_at": "ALTER TABLE parked_topics ADD COLUMN updated_at TEXT",
    }
    for column, ddl in additions.items():
        if column not in existing:
            conn.execute(ddl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS board_columns (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            position INTEGER NOT NULL
        )
        """
    )
    seeded = conn.execute("SELECT COUNT(*) FROM board_columns").fetchone()[0]
    if seeded == 0:
        for position, (key, name) in enumerate(_DEFAULT_BOARD_COLUMNS):
            conn.execute(
                "INSERT INTO board_columns (key, name, position) VALUES (?, ?, ?)",
                (key, name, position),
            )
    conn.commit()


def _slugify_column(name: str) -> str:
    """Turn a human column name into a stable url/key-safe slug.

    "Deep Dive" -> "deep-dive". Lowercased, runs of non-alphanumerics collapse
    to a single hyphen, leading/trailing hyphens trimmed.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return slug.strip("-")


def _column_keys(conn: sqlite3.Connection) -> list[str]:
    """Ordered list of board column keys, left-to-right."""
    return [row["key"] for row in conn.execute("SELECT key FROM board_columns ORDER BY position")]


def _renormalise_column(conn: sqlite3.Connection, column: str) -> None:
    """Rewrite ``board_order`` for a column's pending items to a dense 0..n-1.

    Keeps ordering gap-free so later inserts/moves have no drift to reason
    about. Uses ``(board_order, id)`` as the stable pre-move order.
    """
    ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM parked_topics "
            "WHERE board_column = ? AND status = 'pending' "
            "ORDER BY board_order, id",
            (column,),
        )
    ]
    for order, row_id in enumerate(ids):
        conn.execute(
            "UPDATE parked_topics SET board_order = ? WHERE id = ?",
            (order, row_id),
        )


def _ensure_reference_rows(
    conn: sqlite3.Connection,
    *,
    study_session_id: str | None,
    session_id: str | None,
) -> None:
    """Create minimal FK parent rows for externally supplied session IDs."""
    if session_id:
        conn.execute(
            """INSERT OR IGNORE INTO sessions (id, source, created_at, updated_at)
               VALUES (?, 'studyloop', datetime('now'), datetime('now'))""",
            (session_id,),
        )
    if study_session_id:
        conn.execute(
            """INSERT OR IGNORE INTO study_sessions (id, started_at)
               VALUES (?, datetime('now'))""",
            (study_session_id,),
        )


def park_topic(
    question: str,
    topic_tag: str | None = None,
    context: str | None = None,
    study_session_id: str | None = None,
    session_id: str | None = None,
    created_by: str = "agent",
    source: str = "parked",
    tech_area: str | None = None,
    notes: str | None = None,
    board_column: str = "inbox",
) -> int | None:
    """Park a tangential topic for later. Returns the row ID or None on failure.

    If the topic already has a pending row for this (question, source) pair
    (INSERT OR IGNORE hits the partial unique index), the existing row's ID
    is returned and its park_count is incremented.

    Args:
        source: Origin of the entry — 'parked', 'struggled', or 'manual'.
        tech_area: Technology category (e.g. 'Python', 'SQL').
        notes: Optional Markdown notes; normalised to clean Markdown on the way
            in so the DB only ever holds clean Markdown.
        board_column: Kanban column key the card lands in (default 'inbox').
    """
    clean_notes = normalise_markdown(notes) if notes is not None else None
    try:
        conn = _connect()
        try:
            # Serialise the append's read-modify-write. park_topic reads
            # MAX(board_order)+1 then inserts; without the write lock held
            # across both, two concurrent parks into the same column read the
            # same MAX and write the same board_order (a lost update). Taking
            # the lock up front (BEGIN IMMEDIATE) forces them to serialise.
            with _immediate(conn):
                _ensure_reference_rows(
                    conn,
                    study_session_id=study_session_id,
                    session_id=session_id,
                )
                # Append to the end of the target column (dense 0..n ordering).
                next_order = conn.execute(
                    "SELECT COALESCE(MAX(board_order), -1) + 1 AS n FROM parked_topics "
                    "WHERE board_column = ? AND status = 'pending'",
                    (board_column,),
                ).fetchone()["n"]
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO parked_topics
                       (study_session_id, session_id, topic_tag, question,
                        context, created_by, source, tech_area, notes,
                        board_column, board_order)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        study_session_id,
                        session_id,
                        topic_tag,
                        question,
                        context,
                        created_by,
                        source,
                        tech_area,
                        clean_notes,
                        board_column,
                        next_order,
                    ),
                )
                if cursor.rowcount > 0:
                    return cursor.lastrowid
                # Insert was ignored (duplicate pending) — increment park_count
                # and return existing row ID
                conn.execute(
                    """UPDATE parked_topics SET park_count = park_count + 1
                       WHERE question = ? AND source = ? AND status = 'pending'""",
                    (question, source),
                )
                row = conn.execute(
                    """SELECT id FROM parked_topics
                       WHERE question = ? AND source = ? AND status = 'pending'""",
                    (question, source),
                ).fetchone()
                return row["id"] if row else None
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to park topic: %s", question)
        return None


def get_parked_topics(
    study_session_id: str | None = None,
    status: str = "pending",
    source: str | None = None,
    tech_area: str | None = None,
) -> list[dict]:
    """Get parked topics with optional filters.

    Args:
        study_session_id: Filter by specific study session.
        status: Filter by status (default 'pending').
        source: Filter by source ('parked', 'struggled', 'manual').
        tech_area: Filter by technology area.
    """
    conn = _connect()
    try:
        clauses = ["status = ?"]
        params: list[str] = [status]
        if study_session_id:
            clauses.append("study_session_id = ?")
            params.append(study_session_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if tech_area:
            clauses.append("tech_area = ?")
            params.append(tech_area)
        where = " AND ".join(clauses)
        # `parked_at` has one-second resolution, so topics parked in the same
        # second tie and SQLite may return them in any order -- in practice
        # rowid ascending, i.e. exactly backwards for the DESC case. `id` is
        # INTEGER PRIMARY KEY AUTOINCREMENT, so it is a monotonic stand-in for
        # insertion order and gives a total ordering. Without it, "which three
        # topics am I focused on" could differ between two consecutive reads.
        order = "parked_at, id" if study_session_id else "parked_at DESC, id DESC"
        rows = conn.execute(
            f"SELECT * FROM parked_topics WHERE {where} ORDER BY {order}",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unscheduled_parked_topics(
    topic_tag: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Get pending parked topics for surfacing at session start.

    Ordered newest-first. ``parked_at`` has one-second resolution, so several
    topics parked in the same second compare equal and SQLite is then free to
    return them in any order -- in practice rowid ascending, i.e. exactly
    backwards. ``id DESC`` breaks the tie by insertion order (the column is
    INTEGER PRIMARY KEY AUTOINCREMENT, so it is monotonic), which is what
    "most recent" means when the clock cannot separate them.
    """
    conn = _connect()
    try:
        if topic_tag:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE status = 'pending' AND topic_tag = ?
                   ORDER BY parked_at DESC, id DESC LIMIT ?""",
                (topic_tag, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE status = 'pending'
                   ORDER BY parked_at DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def schedule_parked_topic(parked_id: int, scheduled_for: str) -> bool:
    """Set a date for a parked topic. scheduled_for is ISO date string (YYYY-MM-DD)."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'scheduled', scheduled_for = ?
               WHERE id = ? AND status IN ('pending', 'scheduled')""",
            (scheduled_for, parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def demote_parked_topic(parked_id: int) -> bool:
    """Push a pending topic out of the active window into the parking lot.

    The active/parking split is purely recency-ordered (``parked_at DESC``),
    so "park one to free a slot" = make this row the OLDEST pending entry.
    Re-parking the same question is an INSERT OR IGNORE no-op and would NOT
    move it — this explicit demote is the only correct lever.
    """
    try:
        conn = _connect()
        try:
            cursor = conn.execute(
                """UPDATE parked_topics
                   SET parked_at = (
                       SELECT datetime(MIN(parked_at), '-1 second')
                       FROM parked_topics WHERE status = 'pending'
                   )
                   WHERE id = ? AND status = 'pending'""",
                (parked_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to demote parked topic id=%s", parked_id)
        return False


def resolve_parked_topic(parked_id: int) -> bool:
    """Mark a parked topic as resolved/covered."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'resolved', resolved_at = ?
               WHERE id = ? AND status IN ('pending', 'scheduled')""",
            (datetime.now(UTC).isoformat(), parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def dismiss_parked_topic(parked_id: int) -> bool:
    """Mark a parked topic as dismissed (not worth scheduling)."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'dismissed'
               WHERE id = ? AND status = 'pending'""",
            (parked_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_topic_frequencies(status: str = "pending") -> dict[str, int]:
    """Get the re-park frequency for each question in parked_topics.

    Returns a dict mapping question text to how many times it was parked,
    even across sessions. The v26 partial unique index allows at most one
    pending row per ``(question, source)``, and ``park_count`` on that row
    tracks re-parks — so the frequency for a question is the SUM of
    ``park_count`` across its sources, not a row count.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT question, SUM(park_count) AS freq
               FROM parked_topics WHERE status = ?
               GROUP BY question ORDER BY freq DESC""",
            (status,),
        ).fetchall()
        return {row["question"]: row["freq"] for row in rows}
    finally:
        conn.close()


def update_topic_priority(parked_id: int, priority: int) -> bool:
    """Set the agent-assessed importance (1-5) on a backlog item."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE parked_topics SET priority = ? WHERE id = ?",
            (priority, parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Kanban board layer — columns, grouping, in-place edit, move, clear/restore
# ---------------------------------------------------------------------------


def get_board_columns() -> list[dict]:
    """Return the board's columns left-to-right (without their items)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT key, name, position FROM board_columns ORDER BY position"
        ).fetchall()
        return [{"key": r["key"], "name": r["name"], "position": r["position"]} for r in rows]
    finally:
        conn.close()


def get_board() -> dict:
    """Return the whole board: ordered columns, each with its ordered pending cards.

    An item whose ``board_column`` no longer matches any column (a deleted or
    never-created column) is surfaced in the first column so a user's thought
    can never silently vanish.
    """
    conn = _connect()
    try:
        columns = conn.execute(
            "SELECT key, name FROM board_columns ORDER BY position"
        ).fetchall()
        keys = [c["key"] for c in columns]
        buckets: dict[str, list[dict]] = {c["key"]: [] for c in columns}
        first_key = keys[0] if keys else None

        rows = conn.execute(
            "SELECT * FROM parked_topics WHERE status = 'pending' ORDER BY board_order, id"
        ).fetchall()
        for row in rows:
            key = row["board_column"]
            if key not in buckets:
                key = first_key
            if key is not None:
                buckets[key].append(dict(row))

        return {
            "columns": [
                {"key": c["key"], "name": c["name"], "items": buckets[c["key"]]}
                for c in columns
            ],
            "total": sum(len(items) for items in buckets.values()),
        }
    finally:
        conn.close()


def update_parked_topic(item_id: int, **fields: object) -> dict | None:
    """Edit one card in place. Returns the updated card, or ``None`` if absent.

    Only whitelisted fields are editable; anything else raises ``ValueError``.
    ``notes`` is re-normalised to clean Markdown, ``question`` may not be blank,
    and ``priority`` is clamped to 1..5.
    """
    updates: dict[str, object] = {}
    for key, value in fields.items():
        if key not in _EDITABLE_TOPIC_FIELDS:
            msg = f"Not editable: {key}"
            raise ValueError(msg)
        updates[key] = value
    if not updates:
        msg = "No editable fields supplied"
        raise ValueError(msg)

    if "question" in updates:
        question = str(updates["question"] or "").strip()
        if not question:
            msg = "question cannot be empty"
            raise ValueError(msg)
        updates["question"] = question
    if "notes" in updates:
        updates["notes"] = normalise_markdown(str(updates["notes"]) if updates["notes"] else "")
    if updates.get("priority") is not None:
        updates["priority"] = max(1, min(5, int(updates["priority"])))  # type: ignore[arg-type]

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn = _connect()
    try:
        cursor = conn.execute(
            f"UPDATE parked_topics SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            (*updates.values(), item_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM parked_topics WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def move_parked_topic(item_id: int, board_column: str, position: int | None = None) -> bool:
    """Move a card to ``board_column`` at ``position`` (append when omitted).

    Rejects an unknown column or a missing/non-pending item. Renormalises the
    target (and vacated source) column to a dense 0..n-1 ordering.
    """
    conn = _connect()
    try:
        # Serialise validate → move → reindex under one write lock so two
        # concurrent moves can't interleave and clobber each other's
        # board_order (see _immediate).
        with _immediate(conn):
            if conn.execute(
                "SELECT 1 FROM board_columns WHERE key = ?", (board_column,)
            ).fetchone() is None:
                return False
            current = conn.execute(
                "SELECT board_column FROM parked_topics WHERE id = ? AND status = 'pending'",
                (item_id,),
            ).fetchone()
            if current is None:
                return False
            old_column = current["board_column"]

            conn.execute(
                "UPDATE parked_topics SET board_column = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (board_column, item_id),
            )
            others = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM parked_topics "
                    "WHERE board_column = ? AND status = 'pending' AND id != ? "
                    "ORDER BY board_order, id",
                    (board_column, item_id),
                )
            ]
            if position is None or position >= len(others):
                new_order = [*others, item_id]
            else:
                index = max(0, position)
                new_order = [*others[:index], item_id, *others[index:]]
            for order, row_id in enumerate(new_order):
                conn.execute(
                    "UPDATE parked_topics SET board_order = ? WHERE id = ?",
                    (order, row_id),
                )
            if old_column != board_column:
                _renormalise_column(conn, old_column)
            return True
    finally:
        conn.close()


def clear_parked_topics(ids: list[int], *, hard: bool = False) -> int:
    """Clear the given cards. Soft by default (recoverable), hard on request.

    Returns the number of rows actually affected — so the caller learns that an
    id was already gone. An empty selection is a no-op.
    """
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    conn = _connect()
    try:
        if hard:
            cursor = conn.execute(
                f"DELETE FROM parked_topics WHERE id IN ({placeholders})",
                tuple(ids),
            )
        else:
            cursor = conn.execute(
                f"UPDATE parked_topics SET status = 'dismissed', updated_at = datetime('now') "
                f"WHERE id IN ({placeholders}) AND status = 'pending'",
                tuple(ids),
            )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def clear_all_parked_topics(*, hard: bool = False) -> int:
    """Clear every pending card. Soft by default so "clear all" stays undoable."""
    conn = _connect()
    try:
        if hard:
            cursor = conn.execute("DELETE FROM parked_topics")
        else:
            cursor = conn.execute(
                "UPDATE parked_topics SET status = 'dismissed', updated_at = datetime('now') "
                "WHERE status = 'pending'"
            )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def restore_parked_topic(item_id: int) -> bool:
    """Undo a soft clear: put a dismissed card back on the board."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE parked_topics SET status = 'pending', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'dismissed'",
            (item_id,),
        )
        conn.commit()
        return bool(cursor.rowcount)
    finally:
        conn.close()


def add_board_column(name: str) -> dict | None:
    """Add a user-defined column. Returns the created column, or ``None``.

    The key is a slug of ``name``, de-duplicated against existing keys by
    suffixing ``-2``, ``-3``, … A blank name is rejected.
    """
    clean = (name or "").strip()
    base = _slugify_column(clean)
    if not clean or not base:
        return None
    conn = _connect()
    try:
        existing = {row["key"] for row in conn.execute("SELECT key FROM board_columns")}
        key = base
        suffix = 2
        while key in existing:
            key = f"{base}-{suffix}"
            suffix += 1
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM board_columns"
        ).fetchone()["p"]
        conn.execute(
            "INSERT INTO board_columns (key, name, position) VALUES (?, ?, ?)",
            (key, clean, position),
        )
        conn.commit()
        return {"key": key, "name": clean, "position": position}
    finally:
        conn.close()


def rename_board_column(key: str, name: str) -> bool:
    """Rename a column. Its key — and every card's link to it — stays stable."""
    clean = (name or "").strip()
    if not clean:
        return False
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE board_columns SET name = ? WHERE key = ?",
            (clean, key),
        )
        conn.commit()
        return bool(cursor.rowcount)
    finally:
        conn.close()


def delete_board_column(key: str, move_items_to: str | None = None) -> bool:
    """Delete a column, relocating its cards (never deleting them).

    Cards move to ``move_items_to`` when it is a valid other column, otherwise
    to the first remaining column. Refuses to delete the last column (a
    column-less board is unusable) or an unknown column.
    """
    conn = _connect()
    try:
        keys = _column_keys(conn)
        if key not in keys or len(keys) <= 1:
            return False
        remaining = [k for k in keys if k != key]
        target = move_items_to if move_items_to in remaining else remaining[0]

        conn.execute(
            "UPDATE parked_topics SET board_column = ? WHERE board_column = ?",
            (target, key),
        )
        conn.execute("DELETE FROM board_columns WHERE key = ?", (key,))
        for position, remaining_key in enumerate(remaining):
            conn.execute(
                "UPDATE board_columns SET position = ? WHERE key = ?",
                (position, remaining_key),
            )
        _renormalise_column(conn, target)
        conn.commit()
        return True
    finally:
        conn.close()


def reorder_board_columns(keys: list[str]) -> bool:
    """Persist a new left-to-right column order.

    Unknown keys are ignored; any existing column not named is appended in its
    current relative order, so the board never loses a column. An empty (or
    fully-unknown) request is rejected.
    """
    if not keys:
        return False
    conn = _connect()
    try:
        existing = _column_keys(conn)
        ordered = [k for k in keys if k in existing]
        if not ordered:
            return False
        ordered.extend(k for k in existing if k not in ordered)
        for position, key in enumerate(ordered):
            conn.execute(
                "UPDATE board_columns SET position = ? WHERE key = ?",
                (position, key),
            )
        conn.commit()
        return True
    finally:
        conn.close()
