"""Base classes and protocols for session exporters."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExportStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0  # already up-to-date since last export (unchanged)
    empty: int = 0  # no supported conversation or native records
    errors: int = 0
    forgotten: int = 0  # explicitly retired sessions, never reimported
    withdrawn: int = 0  # permission withheld; only a fresh eligible regrant releases it

    def __iadd__(self, other: "ExportStats") -> "ExportStats":
        self.added += other.added
        self.updated += other.updated
        self.skipped += other.skipped
        self.empty += other.empty
        self.errors += other.errors
        self.forgotten += other.forgotten
        self.withdrawn += other.withdrawn
        return self


class SessionExporter(Protocol):
    """Protocol for session exporters."""

    @property
    def source_name(self) -> str:
        """Unique identifier for this source."""
        ...

    def is_available(self) -> bool:
        """Check if source data is available on system."""
        ...

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions from this source with batching."""
        ...


def commit_batch(
    conn: sqlite3.Connection, sessions: list, messages: list, stats: ExportStats
) -> None:
    """Commit a batch of sessions and messages to the database.

    Sessions and messages are lists of dicts with named keys matching the DB columns.
    Missing optional fields default to NULL via dict.get().
    """
    if not sessions:
        return

    try:
        from ..context.capture import available

        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        forgotten = set()
        if available(conn, "context_tombstones"):
            forgotten = {
                session["id"]
                for session in sessions
                if conn.execute(
                    "SELECT 1 FROM context_tombstones WHERE session_id=?",
                    (session["id"],),
                ).fetchone()
            }
            sessions = [s for s in sessions if s["id"] not in forgotten]
            messages = [m for m in messages if m["session_id"] not in forgotten]
        withdrawn = set()
        if available(conn, "context_replica_denials"):
            withdrawn = {
                s["id"]
                for s in sessions
                if conn.execute(
                    "SELECT 1 FROM context_replica_denials WHERE kind='session' AND object_id=? AND status!='released'",
                    (s["id"],),
                ).fetchone()
            }
            sessions = [s for s in sessions if s["id"] not in withdrawn]
            messages = [m for m in messages if m["session_id"] not in withdrawn]
        if not sessions:
            conn.commit()
            stats.forgotten += len(forgotten)
            stats.withdrawn += len(withdrawn)
            return
        session_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        include_import_fingerprint = "import_fingerprint" in session_columns

        session_insert_columns = [
            "id",
            "source",
            "project_path",
            "git_branch",
            "created_at",
            "updated_at",
            "metadata",
        ]
        if include_import_fingerprint:
            session_insert_columns.insert(6, "import_fingerprint")

        placeholders = ", ".join("?" for _ in session_insert_columns)
        conn.executemany(
            f"""
            INSERT INTO sessions (
                {", ".join(session_insert_columns)}
            ) VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET
                {", ".join(f"{column}=excluded.{column}" for column in session_insert_columns if column != "id")}
        """,
            [  # noqa: C416 - clearer than nested helper for optional columns
                tuple(
                    s.get(column) if column != "id" else s["id"]
                    for column in session_insert_columns
                )
                for s in sessions
            ],
        )

        if messages:
            messages = _preserve_message_identity(conn, messages)
            owners = {}
            for message in messages:
                if (
                    message["id"] in owners
                    and owners[message["id"]] != message["session_id"]
                ):
                    raise ValueError(
                        "Message ID collision within batch: " + message["id"]
                    )
                owners[message["id"]] = message["session_id"]
                owner = conn.execute(
                    "SELECT session_id FROM messages WHERE id = ?", (message["id"],)
                ).fetchone()
                if owner and owner[0] != message["session_id"]:
                    raise ValueError(
                        "Message ID collision across sessions: " + message["id"]
                    )
            conn.executemany(
                """
                INSERT INTO messages (
                    id, session_id, role, content, model, timestamp, metadata, seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    role=excluded.role, content=excluded.content, model=excluded.model,
                    timestamp=COALESCE(excluded.timestamp, messages.timestamp),
                    metadata=excluded.metadata, seq=excluded.seq
            """,
                [
                    (
                        m["id"],
                        m["session_id"],
                        m["role"],
                        m["content"],
                        m.get("model"),
                        m.get("timestamp"),
                        m.get("metadata"),
                        m.get("seq"),
                    )
                    for m in messages
                ],
            )

        for session in sessions:
            if not session.get("replace_messages"):
                continue
            incoming = {m["id"] for m in messages if m["session_id"] == session["id"]}
            # Native histories can compact or expire: keep previously captured
            # prose even when absent from the current source. Only empty legacy
            # parser artefacts are safe to reconcile away automatically.
            stale = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM messages WHERE session_id = ? AND (content IS NULL OR trim(content) = '')",
                    (session["id"],),
                )
                if row[0] not in incoming
            ]
            for message_id in stale:
                if _message_is_referenced(conn, message_id):
                    raise ValueError(
                        "Cannot remove a stale message with evidence references: "
                        + message_id
                    )
                conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))

        from ..context.capture import capture_batch

        capture_batch(conn, sessions, messages)
        conn.commit()
        stats.forgotten += len(forgotten)
        stats.withdrawn += len(withdrawn)
        # Publish counts only after persistence succeeds.
        # Update stats from session status flags
        for s in sessions:
            status = s.get("status", "added")
            if status == "added":
                stats.added += 1
            elif status == "updated":
                stats.updated += 1
            elif status == "skipped":
                stats.skipped += 1
            elif status == "empty":
                stats.empty += 1

    except Exception:
        conn.rollback()
        stats.errors += len(sessions)
        raise


def _message_is_referenced(conn: sqlite3.Connection, message_id: str) -> bool:
    """Protect evidence even when older schemas did not declare a foreign key."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%'"
        )
    ]
    for table in tables:
        if table == "messages":
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({quoted})")}
        for column in columns & {"message_id", "evidence_message_id"}:
            if conn.execute(
                f'SELECT 1 FROM {quoted} WHERE "{column}" = ? LIMIT 1', (message_id,)
            ).fetchone():
                return True
    return False


def _preserve_message_identity(conn: sqlite3.Connection, messages: list) -> list:
    """Do not let a shifted positional ID overwrite historical conversation text."""
    old_by_session = {}
    used = set()
    result = []
    for incoming in messages:
        row = dict(incoming)
        sid = row["session_id"]
        if sid not in old_by_session:
            old_by_session[sid] = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    "SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY rowid",
                    (sid,),
                )
            }
        old = old_by_session[sid]
        content_key = (row["role"], row["content"])
        prior = old.get(row["id"])
        if prior and prior[1] and str(prior[1]).strip() and prior != content_key:
            original_id = row["id"]
            match = next(
                (
                    key
                    for key, value in old.items()
                    if value == content_key and key not in used
                ),
                None,
            )
            if match is None:
                digest = hashlib.sha256(json.dumps(content_key).encode()).hexdigest()[
                    :24
                ]
                match = original_id + "-rev-" + digest
                if match in old and old[match] != content_key:
                    raise ValueError("Revision identity collision")
            row["id"] = match
            metadata = json.loads(row.get("metadata") or "{}")
            metadata["source_record_id"] = original_id
            row["metadata"] = json.dumps(metadata)
        used.add(row["id"])
        result.append(row)
    return result
