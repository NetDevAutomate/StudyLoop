"""Study-notes persistence — structured Markdown the agent can read back.

Why this is a separate module from :mod:`studyloop.parking`:

``parked_topics`` answers *"what should I come back to?"*. A note answers
*"what did I work out, and how well do I actually grasp it?"*. Those have
different lifecycles — a parked topic is closed by being studied, a note is
never closed at all — and overloading one table with both made "what is still
open" unanswerable. So notes get their own table, ``study_notes``.

Three design decisions worth knowing:

* **Markdown in, Markdown out.** Bodies go through
  :func:`studyloop.markdown_notes.normalise_markdown` on every write, so the DB
  only ever holds clean Markdown — no HTML, no bespoke format. A note written
  in a body-double session still opens in Obsidian years later.
* **``kind`` is a contract with the agent, not decoration.** ``plan`` rows are
  what a mentor turns into a structured study plan; ``assessment`` / ``struggle``
  / ``win`` rows plus ``confidence`` are what it reads to judge progress.
  Classifying at capture time means the agent never has to guess from prose.
* **Deletion is soft by default.** ``status='dismissed'`` keeps the row so an
  accidental clear is undoable, exactly like the parking lot. ``hard=True``
  exists for a genuine purge.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from studyloop.db import SCHEMA_LOCK, connect_db
from studyloop.markdown_notes import normalise_markdown, summarise_markdown
from studyloop.settings import get_db_path

logger = logging.getLogger(__name__)

__all__ = [
    "NOTE_KINDS",
    "add_note",
    "clear_all_notes",
    "clear_notes",
    "count_notes",
    "get_note",
    "list_notes",
    "notes_markdown",
    "restore_note",
    "update_note",
]

#: The closed set of note kinds. Kept in Python (not only in the CHECK
#: constraint) so the API layer can validate before touching the DB and return
#: 422 rather than a 500 from a constraint violation.
NOTE_KINDS: tuple[str, ...] = (
    "note",
    "question",
    "plan",
    "assessment",
    "win",
    "struggle",
)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS study_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    topic TEXT,
    kind TEXT NOT NULL DEFAULT 'note'
        CHECK(kind IN ('note', 'question', 'plan', 'assessment', 'win', 'struggle')),
    confidence INTEGER,
    origin TEXT NOT NULL DEFAULT 'body-double',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'dismissed')),
    created_by TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
)
"""

_EDITABLE = ("title", "body", "topic", "kind", "confidence")


def _connect() -> sqlite3.Connection:
    """Open the session DB with ``study_notes`` guaranteed to exist.

    Mirrors :func:`studyloop.parking._connect` deliberately, including its
    self-healing CREATE: ``PRAGMA user_version`` can run ahead of the real
    schema when a migration partially applies, and when that happens the
    migration system *skips* the CREATE because it believes it already ran.
    Checking for the table directly is the only reliable recovery.
    """
    with SCHEMA_LOCK:
        conn = connect_db(get_db_path(), row_factory=True)

        # Base schema first. On a DB whose first writer is the notes panel there is
        # no `sessions`/`study_sessions` table yet, so the FK targets below would
        # not exist and every INSERT would fail under PRAGMA foreign_keys=ON.
        #
        # This used to import `ensure_schema` from studyloop.history._connection,
        # which does not exist — the ImportError was swallowed by the except, so
        # the healing never ran. init_db applies the canonical schema.sql and
        # runs migrations; reconnect after, since it returns its own connection.
        try:
            conn.execute("SELECT 1 FROM sessions LIMIT 0")
        except sqlite3.OperationalError:
            logger.info("Initialising base session schema for study_notes")
            conn.close()
            try:
                from agent_session_tools.export_sessions import init_db

                init_db(str(get_db_path())).close()
            except Exception:
                logger.warning("Base schema init failed for study_notes", exc_info=True)
            conn = connect_db(get_db_path(), row_factory=True)

        try:
            conn.execute("SELECT 1 FROM study_notes LIMIT 0")
        except sqlite3.OperationalError:
            logger.info("Creating study_notes table directly (migration drift recovery)")
            conn.execute(_TABLE_DDL)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_study_notes_status "
                "ON study_notes(status, created_at DESC)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_study_notes_topic ON study_notes(topic)")
            conn.commit()

    return conn


def _ensure_reference_rows(
    conn: sqlite3.Connection,
    *,
    study_session_id: str | None,
    session_id: str | None,
) -> None:
    """Create minimal FK parent rows for externally supplied session IDs.

    The web layer knows a ``study_session_id`` before the history layer has
    necessarily written its row; without this a note taken in the first seconds
    of a session would be rejected by the foreign key.
    """
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


def _row_to_note(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a DB row into the dict shape the API and TUI both consume."""
    body = row["body"] or ""
    return {
        "id": row["id"],
        "title": row["title"],
        "body": body,
        "topic": row["topic"],
        "kind": row["kind"],
        "confidence": row["confidence"],
        "origin": row["origin"],
        "status": row["status"],
        "study_session_id": row["study_session_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "preview": summarise_markdown(body),
        "body_chars": len(body),
    }


def add_note(
    title: str,
    *,
    body: str | None = None,
    topic: str | None = None,
    kind: str = "note",
    confidence: int | None = None,
    origin: str = "body-double",
    study_session_id: str | None = None,
    session_id: str | None = None,
    created_by: str = "web",
) -> int | None:
    """Store one note. Returns its row id, or ``None`` when the write failed.

    ``body`` is normalised to clean Markdown before it is stored — the caller
    never has to get fence or whitespace hygiene right.
    """
    title = (title or "").strip()
    if not title:
        return None
    if kind not in NOTE_KINDS:
        kind = "note"
    clean_body = normalise_markdown(body or "")
    conn = _connect()
    try:
        _ensure_reference_rows(conn, study_session_id=study_session_id, session_id=session_id)
        cursor = conn.execute(
            """INSERT INTO study_notes
                   (study_session_id, session_id, title, body, topic, kind,
                    confidence, origin, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                study_session_id,
                session_id,
                title,
                clean_body,
                topic,
                kind,
                confidence,
                origin,
                created_by,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid) if cursor.lastrowid else None
    except sqlite3.Error:
        logger.exception("Could not store study note")
        return None
    finally:
        conn.close()


def list_notes(
    *,
    status: str = "active",
    topic: str | None = None,
    kind: str | None = None,
    study_session_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return notes newest-first, optionally filtered.

    ``status='all'`` includes soft-cleared rows — the only way to see what an
    undo would restore.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if study_session_id:
        clauses.append("study_session_id = ?")
        params.append(study_session_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _connect()
    try:
        # `id DESC` is not decoration: `created_at` has second granularity, so
        # notes written in the same second would otherwise come back in an
        # arbitrary order and "newest first" would not be stable between reads.
        #

        # names above; every value is a bound parameter.
        query = (
            f"SELECT * FROM study_notes {where} ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
        )
        rows = conn.execute(query, (*params, limit)).fetchall()
        return [_row_to_note(row) for row in rows]
    except sqlite3.Error:
        logger.exception("Could not list study notes")
        return []
    finally:
        conn.close()


def count_notes(*, status: str = "active") -> int:
    """Count notes with the given status (``'all'`` counts everything)."""
    conn = _connect()
    try:
        if status == "all":
            row = conn.execute("SELECT COUNT(*) AS n FROM study_notes").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM study_notes WHERE status = ?", (status,)
            ).fetchone()
        return int(row["n"]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def get_note(note_id: int) -> dict[str, Any] | None:
    """Return one note by id, or ``None`` when it does not exist."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM study_notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_note(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def update_note(note_id: int, **fields: Any) -> dict[str, Any] | None:
    """Patch one note in place. Returns the updated note, or ``None`` if absent.

    Only the caller-supplied fields are written, so two edits to different
    fields of the same note cannot clobber each other. ``body`` is re-normalised
    on the way in.
    """
    updates = {k: v for k, v in fields.items() if k in _EDITABLE}
    if not updates:
        msg = "No editable fields supplied"
        raise ValueError(msg)
    if "kind" in updates and updates["kind"] not in NOTE_KINDS:
        msg = f"Unknown note kind: {updates['kind']!r}"
        raise ValueError(msg)
    if "title" in updates:
        title = (updates["title"] or "").strip()
        if not title:
            msg = "Title cannot be empty"
            raise ValueError(msg)
        updates["title"] = title
    if "body" in updates:
        updates["body"] = normalise_markdown(updates["body"] or "")
    if "confidence" in updates and updates["confidence"] is not None:
        confidence = int(updates["confidence"])
        if not 1 <= confidence <= 5:
            msg = "Confidence must be between 1 and 5"
            raise ValueError(msg)
        updates["confidence"] = confidence

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn = _connect()
    try:
        cursor = conn.execute(
            f"UPDATE study_notes SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            (*updates.values(), note_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM study_notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_note(row) if row else None
    except sqlite3.Error:
        logger.exception("Could not update study note %s", note_id)
        return None
    finally:
        conn.close()


def clear_notes(ids: list[int], *, hard: bool = False) -> int:
    """Clear the given notes. Soft by default (recoverable), hard on request.

    Returns the number of rows actually affected — which is how the caller
    learns that an id was already gone.
    """
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    conn = _connect()
    try:
        if hard:
            cursor = conn.execute(
                f"DELETE FROM study_notes WHERE id IN ({placeholders})",
                tuple(ids),
            )
        else:
            cursor = conn.execute(
                f"UPDATE study_notes SET status = 'dismissed', updated_at = datetime('now') "
                f"WHERE id IN ({placeholders}) AND status = 'active'",
                tuple(ids),
            )
        conn.commit()
        return int(cursor.rowcount or 0)
    except sqlite3.Error:
        logger.exception("Could not clear study notes")
        return 0
    finally:
        conn.close()


def clear_all_notes(*, hard: bool = False) -> int:
    """Clear every active note. Soft by default so "clear all" stays undoable."""
    conn = _connect()
    try:
        if hard:
            cursor = conn.execute("DELETE FROM study_notes")
        else:
            cursor = conn.execute(
                "UPDATE study_notes SET status = 'dismissed', updated_at = datetime('now') "
                "WHERE status = 'active'"
            )
        conn.commit()
        return int(cursor.rowcount or 0)
    except sqlite3.Error:
        logger.exception("Could not clear all study notes")
        return 0
    finally:
        conn.close()


def restore_note(note_id: int) -> bool:
    """Undo a soft clear for one note."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE study_notes SET status = 'active', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'dismissed'",
            (note_id,),
        )
        conn.commit()
        return bool(cursor.rowcount)
    except sqlite3.Error:
        logger.exception("Could not restore study note %s", note_id)
        return False
    finally:
        conn.close()


_KIND_HEADINGS: dict[str, str] = {
    "plan": "Study plan",
    "assessment": "Assessment",
    "question": "Open questions",
    "struggle": "Struggles",
    "win": "Wins",
    "note": "Notes",
}

#: Order sections so an agent reading the export top-to-bottom sees intent
#: (plan) before evidence (assessment/struggle/win) before raw material.
_KIND_ORDER: tuple[str, ...] = ("plan", "assessment", "struggle", "win", "question", "note")

_ATX_HEADING_RE = re.compile(r"^(#{1,6})(\s+\S.*)$")


def _demote_headings(body: str, *, levels: int = 2) -> str:
    """Push a note body's ATX headings down ``levels`` so they nest correctly.

    A note body is written standalone, so it reasonably starts at ``##``. Dropped
    verbatim under a ``### <note title>`` in the export, that ``##`` would jump
    back *above* its own title and an agent parsing by heading depth would read
    the note's first section as a sibling of "Study plan". Demoting by two puts a
    body ``##`` at ``####`` — exactly one level under its own ``###`` title, so
    the document is a valid tree with no skipped levels.

    Content inside fenced code blocks is left byte-identical — a ``#`` there is a
    comment or a shell prompt, not a heading. Headings already at depth 6 stay
    put, because there is no ``#######`` in Markdown.
    """
    if not body:
        return body
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in body.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        match = _ATX_HEADING_RE.match(line)
        if match:
            depth = min(len(match.group(1)) + levels, 6)
            out.append("#" * depth + match.group(2))
        else:
            out.append(line)
    return "\n".join(out)


def notes_markdown(
    *,
    topic: str | None = None,
    study_session_id: str | None = None,
    limit: int = 200,
) -> str:
    """Render active notes as one grouped Markdown document.

    This is the agent-facing view: a mentor asked to "build a study plan from
    my notes" or "assess where I am" reads this instead of issuing six queries
    and re-deriving the grouping. Sections are ordered intent-first
    (:data:`_KIND_ORDER`) and each note keeps its own body verbatim, so
    diagrams and code fences survive.
    """
    notes = list_notes(topic=topic, study_session_id=study_session_id, limit=limit)
    if not notes:
        return "# Study notes\n\n_No notes recorded yet._\n"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        grouped.setdefault(note["kind"], []).append(note)

    lines: list[str] = ["# Study notes"]
    if topic:
        lines.append(f"\nTopic: **{topic}**")
    lines.append("")

    for kind in _KIND_ORDER:
        bucket = grouped.get(kind)
        if not bucket:
            continue
        lines.append(f"## {_KIND_HEADINGS.get(kind, kind.title())}")
        lines.append("")
        for note in bucket:
            meta: list[str] = []
            if note["topic"] and not topic:
                meta.append(f"topic: {note['topic']}")
            if note["confidence"] is not None:
                meta.append(f"confidence: {note['confidence']}/5")
            if note["created_at"]:
                meta.append(f"captured: {note['created_at']}")
            lines.append(f"### {note['title']}")
            if meta:
                lines.append("")
                lines.append(f"_{' · '.join(meta)}_")
            if note["body"]:
                lines.append("")
                lines.append(_demote_headings(note["body"].rstrip()))
            lines.append("")

    return normalise_markdown("\n".join(lines))
