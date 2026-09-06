"""Parking lot persistence — store and manage tangential topics for future sessions.

During a study session, the AI agent parks tangential questions here.
At session start, unresolved parked topics are surfaced via ``studyloop resume``.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime

from agent_session_tools.context import records
from agent_session_tools.context.scope import ScopeError
from studyloop.db import SCHEMA_LOCK
from studyloop.history._connection import owned_write
from studyloop.markdown_notes import normalise_markdown
from studyloop.settings import get_db_path

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
    """Open canonical schema and seed only the explicitly requested board boundary."""
    with SCHEMA_LOCK:
        conn = records.connect(get_db_path())
        try:
            with owned_write(conn):
                scope = records.request_scope(conn)
                if not conn.execute(
                    "SELECT 1 FROM context_board_columns WHERE scope=? LIMIT 1", (scope,)
                ).fetchone():
                    conn.executemany(
                        "INSERT INTO context_board_columns(scope,key,name,position) "
                        "VALUES (?,?,?,?)",
                        [
                            (scope, key, name, index)
                            for index, (key, name) in enumerate(_DEFAULT_BOARD_COLUMNS)
                        ],
                    )
            return conn
        except BaseException:
            conn.close()
            raise


def _resolve_board_column(conn: sqlite3.Connection, requested: str) -> str:
    """Return ``requested`` if it is a live column, else the board's first column.

    Call this INSIDE the write transaction that stores the value. The routes
    validate ``board_column`` up front to give the user a clean 400, but that
    check runs on its own connection and finishes before the write starts, so a
    column deleted in between would still be stored -- there is no foreign key to
    catch it. The card then sits under a key no column owns, invisible on a board
    that groups by column.

    Resolving rather than raising is deliberate. Only the web route lets the user
    choose a column; the CLI, MCP and backlog callers take the ``'inbox'``
    default, and ``delete_board_column`` will happily delete ``inbox`` as long as
    it is not the last one. Raising would turn someone else's column deletion
    into a failure for a caller that never picked a column. Keeping the card and
    putting it in a real column is what the UI already pretended happened.
    """
    keys = _column_keys(conn)
    if requested in keys:
        return requested
    if keys:
        logger.info("board_column %r no longer exists; storing card in %r", requested, keys[0])
        return keys[0]
    return requested


def ensure_schema() -> None:
    """Apply canonical migrations and seed this scope's default board columns.

    A failed migration propagates; this does not repair arbitrary schema drift.
    """
    _connect().close()


def _create_parked_topics_table(conn: sqlite3.Connection) -> None:
    """Compatibility entry point: canonical migrations own the complete schema."""
    from agent_session_tools.migrations import migrate

    migrate(conn)


def _ensure_board_schema(conn: sqlite3.Connection) -> None:
    """Compatibility entry point; no ad hoc schema or global board seed."""
    from agent_session_tools.migrations import migrate

    migrate(conn)


def _slugify_column(name: str) -> str:
    """Turn a human column name into a stable url/key-safe slug.

    "Deep Dive" -> "deep-dive". Lowercased, runs of non-alphanumerics collapse
    to a single hyphen, leading/trailing hyphens trimmed.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return slug.strip("-")


def _column_keys(conn: sqlite3.Connection) -> list[str]:
    return [row["key"] for row in _board_rows(conn)]


def _renormalise_column(conn: sqlite3.Connection, column: str) -> None:
    for order, row in enumerate(
        _read(
            conn, "id", "board_column=? AND status='pending'", [column], "ORDER BY board_order,id"
        )
    ):
        _change(conn, "board_order=?", [order], "id=?", [row["id"]])


def _ensure_reference_rows(conn, *, study_session_id, session_id):
    records.ensure_study_reference(conn, study_session_id=study_session_id, session_id=session_id)


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
    """Re-park only identical ownership/lineage; retain differing source contexts."""
    clean_notes = normalise_markdown(notes) if notes is not None else None
    conn = _connect()
    try:
        with owned_write(conn):
            _ensure_reference_rows(conn, study_session_id=study_session_id, session_id=session_id)
            key = records.owner_key(conn, session_id=session_id, study_session_id=study_session_id)
            duplicate = _read(
                conn,
                "id",
                "question=? AND source=? AND owner_key=? AND status='pending'",
                [question, source, key],
            )
            if duplicate:
                identity = duplicate[0]["id"]
                _change(conn, "park_count=park_count+1", [], "id=?", [identity])
                return identity
            board_column = _resolve_board_column(conn, board_column)
            position = _read(
                conn,
                "COALESCE(MAX(board_order),-1)+1 AS n",
                "board_column=? AND status='pending'",
                [board_column],
            )[0]["n"]
            cursor = conn.execute(
                """INSERT INTO parked_topics
                (study_session_id,session_id,topic_tag,question,context,created_by,source,tech_area,notes,board_column,board_order,owner_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    position,
                    key,
                ),
            )
            assert cursor.lastrowid is not None
            records.bind(
                conn,
                "parked_topics",
                cursor.lastrowid,
                session_id=session_id,
                study_session_id=study_session_id,
            )
            return cursor.lastrowid
    except ScopeError:
        raise
    except sqlite3.Error:
        logger.exception("Failed to park a topic")
        return None
    finally:
        conn.close()


def get_parked_topics(
    study_session_id: str | None = None,
    status: str = "pending",
    source: str | None = None,
    tech_area: str | None = None,
) -> list[dict]:
    conn = _connect()
    try:
        clauses, params = ["status=?"], [status]
        for column, value in [
            ("study_session_id", study_session_id),
            ("source", source),
            ("tech_area", tech_area),
        ]:
            if value:
                clauses.append(column + "=?")
                params.append(value)
        order = "ORDER BY parked_at,id" if study_session_id else "ORDER BY parked_at DESC,id DESC"
        return [dict(row) for row in _read(conn, "*", " AND ".join(clauses), params, order)]
    finally:
        conn.close()


def get_unscheduled_parked_topics(topic_tag: str | None = None, limit: int = 10) -> list[dict]:
    conn = _connect()
    try:
        where, params = "status='pending'", []
        if topic_tag:
            where += " AND topic_tag=?"
            params.append(topic_tag)
        return [
            dict(row)
            for row in _read(
                conn, "*", where, [*params, limit], "ORDER BY parked_at DESC,id DESC LIMIT ?"
            )
        ]
    finally:
        conn.close()


def schedule_parked_topic(parked_id: int, scheduled_for: str) -> bool:
    return _mutate(
        "status='scheduled',scheduled_for=?",
        [scheduled_for],
        "id=? AND status IN ('pending','scheduled')",
        [parked_id],
    )


def demote_parked_topic(parked_id: int) -> bool:
    conn = _connect()
    try:
        with owned_write(conn):
            oldest = _read(
                conn, "datetime(MIN(parked_at),'-1 second') AS oldest", "status='pending'"
            )[0]["oldest"]
            return bool(
                _change(
                    conn, "parked_at=?", [oldest], "id=? AND status='pending'", [parked_id]
                ).rowcount
            )
    finally:
        conn.close()


def resolve_parked_topic(parked_id: int) -> bool:
    return _mutate(
        "status='resolved',resolved_at=?",
        [datetime.now(UTC).isoformat()],
        "id=? AND status IN ('pending','scheduled')",
        [parked_id],
    )


def dismiss_parked_topic(parked_id: int) -> bool:
    return _mutate("status='dismissed'", [], "id=? AND status='pending'", [parked_id])


def get_topic_frequencies(status: str = "pending") -> dict[str, int]:
    """Sum permitted repeated records after ownership and dependency filtering."""
    conn = _connect()
    try:
        return {
            row["question"]: row["freq"]
            for row in _read(
                conn,
                "question,SUM(park_count) AS freq",
                "status=?",
                [status],
                "GROUP BY question ORDER BY freq DESC",
            )
        }
    finally:
        conn.close()


def update_topic_priority(parked_id: int, priority: int) -> bool:
    return _mutate("priority=?", [priority], "id=?", [parked_id])


# ---------------------------------------------------------------------------
# Kanban board layer — columns, grouping, in-place edit, move, clear/restore
# ---------------------------------------------------------------------------


def get_board_columns() -> list[dict]:
    conn = _connect()
    try:
        return [dict(row) for row in _board_rows(conn)]
    finally:
        conn.close()


def get_board() -> dict:
    conn = _connect()
    try:
        columns = _board_rows(conn)
        keys = [row["key"] for row in columns]
        buckets = {key: [] for key in keys}
        for row in _read(conn, "*", "status='pending'", [], "ORDER BY board_order,id"):
            key = (
                row["board_column"]
                if row["board_column"] in buckets
                else (keys[0] if keys else None)
            )
            if key is not None:
                buckets[key].append(dict(row))
        return {
            "columns": [
                {"key": row["key"], "name": row["name"], "items": buckets[row["key"]]}
                for row in columns
            ],
            "total": sum(map(len, buckets.values())),
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

    conn = _connect()
    try:
        with owned_write(conn):
            if not records.is_visible(conn, "parked_topics", item_id):
                return None
            if "board_column" in updates:
                updates["board_column"] = _resolve_board_column(conn, str(updates["board_column"]))
            assignments = ", ".join(column + "=?" for column in updates)
            _change(
                conn,
                assignments + ",updated_at=datetime('now')",
                list(updates.values()),
                "id=?",
                [item_id],
            )
            rows = _read(conn, "*", "id=?", [item_id])
            return dict(rows[0]) if rows else None
    finally:
        conn.close()


def move_parked_topic(item_id: int, board_column: str, position: int | None = None) -> bool:
    conn = _connect()
    try:
        with owned_write(conn):
            if board_column not in _column_keys(conn):
                return False
            current = _read(conn, "board_column", "id=? AND status='pending'", [item_id])
            if not current:
                return False
            old = current[0]["board_column"]
            _change(
                conn, "board_column=?,updated_at=datetime('now')", [board_column], "id=?", [item_id]
            )
            others = [
                row["id"]
                for row in _read(
                    conn,
                    "id",
                    "board_column=? AND status='pending' AND id!=?",
                    [board_column, item_id],
                    "ORDER BY board_order,id",
                )
            ]
            index = len(others) if position is None else max(0, min(position, len(others)))
            others.insert(index, item_id)
            for order, identity in enumerate(others):
                _change(conn, "board_order=?", [order], "id=?", [identity])
            if old != board_column:
                _renormalise_column(conn, old)
            return True
    finally:
        conn.close()


def clear_parked_topics(ids: list[int], *, hard: bool = False) -> int:
    if not ids:
        return 0
    return _clear("id IN (" + ",".join("?" for _ in ids) + ")", ids, hard=hard)


def clear_all_parked_topics(*, hard: bool = False) -> int:
    return _clear("1", [], hard=hard)


def restore_parked_topic(item_id: int) -> bool:
    return _mutate(
        "status='pending',updated_at=datetime('now')", [], "id=? AND status='dismissed'", [item_id]
    )


def add_board_column(name: str) -> dict | None:
    clean = (name or "").strip()
    base = _slugify_column(clean)
    if not clean or not base:
        return None
    conn = _connect()
    try:
        with owned_write(conn):
            rows = _board_rows(conn)
            existing = {row["key"] for row in rows}
            key, suffix = base, 2
            while key in existing:
                key = f"{base}-{suffix}"
                suffix += 1
            position = max((row["position"] for row in rows), default=-1) + 1
            conn.execute(
                "INSERT INTO context_board_columns(scope,key,name,position) VALUES (?,?,?,?)",
                (records.request_scope(conn), key, clean, position),
            )
            return {"key": key, "name": clean, "position": position}
    finally:
        conn.close()


def rename_board_column(key: str, name: str) -> bool:
    clean = (name or "").strip()
    if not clean:
        return False
    conn = _connect()
    try:
        with owned_write(conn):
            return bool(
                conn.execute(
                    "UPDATE context_board_columns SET name=? WHERE scope=? AND key=?",
                    (clean, records.request_scope(conn), key),
                ).rowcount
            )
    finally:
        conn.close()


def delete_board_column(key: str, move_items_to: str | None = None) -> bool:
    conn = _connect()
    try:
        with owned_write(conn):
            keys = _column_keys(conn)
            if key not in keys or len(keys) <= 1:
                return False
            remaining = [k for k in keys if k != key]
            target = move_items_to if move_items_to in remaining else remaining[0]
            _change(conn, "board_column=?", [target], "board_column=?", [key])
            scope = records.request_scope(conn)
            conn.execute("DELETE FROM context_board_columns WHERE scope=? AND key=?", (scope, key))
            for index, column in enumerate(remaining):
                conn.execute(
                    "UPDATE context_board_columns SET position=? WHERE scope=? AND key=?",
                    (index, scope, column),
                )
            _renormalise_column(conn, target)
            return True
    finally:
        conn.close()


def reorder_board_columns(keys: list[str]) -> bool:
    if not keys:
        return False
    conn = _connect()
    try:
        with owned_write(conn):
            existing = _column_keys(conn)
            ordered = list(dict.fromkeys(k for k in keys if k in existing))
            if not ordered:
                return False
            ordered.extend(k for k in existing if k not in ordered)
            scope = records.request_scope(conn)
            for position, key in enumerate(ordered):
                conn.execute(
                    "UPDATE context_board_columns SET position=? WHERE scope=? AND key=?",
                    (position, scope, key),
                )
            return True
    finally:
        conn.close()


def _read(conn, selection="*", where="1", params=(), suffix=""):
    # Fragments are internal call-site SQL; every external value stays bound.
    clause, scope_params = records.visible_sql(conn, "parked_topics", "parked_topics.id")
    return conn.execute(
        "SELECT "
        + selection
        + " FROM parked_topics WHERE ("
        + clause
        + ") AND ("
        + where
        + ") "
        + suffix,
        [*scope_params, *params],
    ).fetchall()


def _change(conn, assignments, values=(), where="1", params=(), *, delete=False):
    clause, scope_params = records.visible_sql(conn, "parked_topics", "parked_topics.id")
    verb = "DELETE FROM parked_topics" if delete else "UPDATE parked_topics SET " + assignments
    return conn.execute(
        verb + " WHERE (" + clause + ") AND (" + where + ")", [*values, *scope_params, *params]
    )


def _mutate(assignments, values, where, params):
    conn = _connect()
    try:
        with owned_write(conn):
            return bool(_change(conn, assignments, values, where, params).rowcount)
    finally:
        conn.close()


def _clear(where, params, *, hard):
    conn = _connect()
    try:
        with owned_write(conn):
            if not hard:
                where += " AND status='pending'"
            return _change(
                conn,
                "status='dismissed',updated_at=datetime('now')",
                [],
                where,
                params,
                delete=hard,
            ).rowcount
    finally:
        conn.close()


def _board_rows(conn):
    return conn.execute(
        "SELECT key,name,position FROM context_board_columns WHERE scope=? ORDER BY position,key",
        (records.request_scope(conn),),
    ).fetchall()
