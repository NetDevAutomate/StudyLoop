"""Trusted exporter integration and body-free capture receipts."""

from __future__ import annotations

import socket
from functools import wraps
from uuid import uuid4

from .scope import _audit, active_policy
from .store import ContextStore, _hash, _now


def install(conn) -> None:
    conn.execute("""CREATE TABLE context_native_message_sources (
      message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
      evidence_id TEXT NOT NULL REFERENCES context_evidence(id) ON DELETE CASCADE,
      rendered_body_sha256 TEXT NOT NULL,
      PRIMARY KEY(message_id,evidence_id))""")
    conn.execute(
        "CREATE INDEX context_native_message_evidence ON context_native_message_sources(evidence_id)"
    )
    conn.execute("""CREATE TRIGGER context_native_links_immutable BEFORE UPDATE
      ON context_native_message_sources BEGIN
      SELECT RAISE(ABORT, 'Native rendering links are immutable'); END""")
    conn.execute("""CREATE TABLE context_capture_runs (
      id TEXT PRIMARY KEY NOT NULL, harness TEXT NOT NULL, parser_version TEXT NOT NULL,
      capture_machine TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
      outcome TEXT NOT NULL CHECK(outcome IN ('started','completed','partial','failed','unavailable')),
      added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
      skipped INTEGER NOT NULL DEFAULT 0, empty INTEGER NOT NULL DEFAULT 0,
      errors INTEGER NOT NULL DEFAULT 0, forgotten INTEGER NOT NULL DEFAULT 0,
      error_class TEXT)""")
    conn.execute(
        "CREATE INDEX context_capture_harness ON context_capture_runs(harness,started_at)"
    )


def available(conn, name: str = "context_evidence") -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def capture_batch(conn, sessions: list[dict], messages: list[dict]) -> None:
    """Append native evidence in the same transaction as its legacy projection."""
    if not available(conn):
        return
    if not any("native_sources" in session for session in sessions):
        _assign_applied_roots(conn, sessions)
        return
    store = ContextStore(conn)
    owners = {session["id"]: session["source"] for session in sessions}
    for session in sessions:
        for source in session.get("native_sources", []):
            if (
                source.session_id != session["id"]
                or source.harness != session["source"]
            ):
                raise ValueError("Native capture owner does not match its session")
            store.capture(source)
    if available(conn, "context_native_message_sources"):
        for message in messages:
            for source in message.get("native_sources", []):
                if source.session_id != message[
                    "session_id"
                ] or source.harness != owners.get(message["session_id"]):
                    raise ValueError(
                        "Native rendering source belongs to another session"
                    )
                identity = store.capture(source)
                conn.execute(
                    "INSERT OR IGNORE INTO context_native_message_sources VALUES (?,?,?)",
                    (message["id"], identity, _hash(message["content"] or "")),
                )
    _assign_applied_roots(conn, sessions)


def _assign_applied_roots(conn, sessions: list[dict]) -> None:
    """Apply an already approved root policy to captured sessions.

    Config drift is never implicitly approved by capture. Existing explicit/sync
    ownership remains authoritative; the operator's policy apply handles changes.
    """
    if not available(conn, "context_policy_state"):
        return
    policy = active_policy()
    head = conn.execute("SELECT digest FROM context_policy_state WHERE id=1").fetchone()
    if head is None or head[0] != policy.digest:
        return
    for session in sessions:
        previous = conn.execute(
            "SELECT project_id,assignment_kind FROM context_session_projects WHERE session_id=?",
            (session["id"],),
        ).fetchone()
        if previous and previous[1] != "root_policy":
            continue
        project = policy.project_for_path(session.get("project_path"))
        before = list(previous) if previous else None
        after = [project.id, "root_policy"] if project else None
        if before == after:
            continue
        if after is None:
            conn.execute(
                "DELETE FROM context_session_projects WHERE session_id=?",
                (session["id"],),
            )
        else:
            conn.execute(
                "INSERT INTO context_session_projects(session_id,project_id,assignment_kind) "
                "VALUES (?,?,'root_policy') ON CONFLICT(session_id) DO UPDATE SET "
                "project_id=excluded.project_id,assignment_kind=excluded.assignment_kind",
                (session["id"], after[0]),
            )
        _audit(
            conn,
            action="session",
            subject=session["id"],
            before=before,
            after=after,
            actor="native-capture",
            digest=policy.digest,
        )


def capture_run(parser_version: str):
    """Track exporter attempts without saving error bodies, credentials or inputs."""

    def decorate(export):
        @wraps(export)
        def wrapped(self, conn, *args, **kwargs):
            if not available(conn, "context_capture_runs"):
                return export(self, conn, *args, **kwargs)
            if conn.in_transaction:
                raise ValueError(
                    "Native export requires a connection without a caller transaction"
                )
            conn.execute("PRAGMA foreign_keys=ON")
            identity = uuid4().hex
            conn.execute(
                """INSERT INTO context_capture_runs
              (id,harness,parser_version,capture_machine,started_at,outcome)
              VALUES (?,?,?,?,?,'started')""",
                (
                    identity,
                    self.source_name,
                    parser_version,
                    socket.gethostname(),
                    _now(),
                ),
            )
            conn.commit()
            try:
                stats = export(self, conn, *args, **kwargs)
            except BaseException as exc:
                conn.rollback()
                if not isinstance(exc, Exception):
                    # Keep the durable attempt incomplete, but never leave an
                    # interrupted batch available for a later accidental commit.
                    raise
                conn.execute(
                    "UPDATE context_capture_runs SET outcome='failed',finished_at=?,errors=1,error_class=? WHERE id=?",
                    (_now(), type(exc).__name__, identity),
                )
                conn.commit()
                raise
            outcome = (
                "unavailable"
                if not self.is_available()
                else "partial"
                if stats.errors
                else "completed"
            )
            conn.execute(
                """UPDATE context_capture_runs SET outcome=?,finished_at=?,
              added=?,updated=?,skipped=?,empty=?,errors=?,forgotten=? WHERE id=?""",
                (
                    outcome,
                    _now(),
                    stats.added,
                    stats.updated,
                    stats.skipped,
                    stats.empty,
                    stats.errors,
                    stats.forgotten,
                    identity,
                ),
            )
            conn.commit()
            return stats

        return wrapped

    return decorate


NATIVE_PARSERS = {
    "codex": "codex-native-v1",
    "claude_code": "claude-native-v1",
    "kiro_cli": "kiro-native-v1",
    "grok": "grok-native-v1",
}


def capture_health(conn) -> dict:
    """Operator diagnostics, without bodies, paths or inferred hook liveness.

    A completed attempt is distinct from a successful hook installation and from
    complete coverage of native archives. This query cannot prove either of those.
    """
    if not available(conn, "context_capture_runs"):
        return {"status": "migration_required", "harnesses": []}
    # Pin the several aggregates to one snapshot without claiming a caller's TX.
    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN")
    try:
        harnesses = []
        for harness, parser in NATIVE_PARSERS.items():
            attempt = conn.execute(
                "SELECT outcome,started_at,finished_at,parser_version,added,updated,"
                "skipped,empty,errors,forgotten,error_class FROM context_capture_runs "
                "WHERE harness=? ORDER BY started_at DESC,rowid DESC LIMIT 1",
                (harness,),
            ).fetchone()
            keys = (
                "outcome",
                "started_at",
                "finished_at",
                "parser_version",
                "added",
                "updated",
                "skipped",
                "empty",
                "errors",
                "forgotten",
                "error_class",
            )
            legacy = conn.execute(
                "SELECT count(*) FROM sessions s WHERE source=? "
                "AND NOT EXISTS (SELECT 1 FROM context_tombstones t WHERE t.session_id=s.id) "
                "AND NOT EXISTS (SELECT 1 FROM context_evidence e WHERE e.session_id=s.id "
                "AND e.parser_version=?)",
                (harness, parser),
            ).fetchone()[0]
            native = conn.execute(
                "SELECT count(*),count(DISTINCT e.session_id),max(e.recorded_at),max(e.first_captured_at) "
                "FROM context_evidence e WHERE e.harness=? AND e.parser_version=? "
                "AND NOT EXISTS (SELECT 1 FROM context_tombstones t WHERE t.session_id=e.session_id)",
                (harness, parser),
            ).fetchone()
            origins = dict(
                conn.execute(
                    "SELECT origin,count(*) FROM context_evidence e WHERE harness=? AND parser_version=? "
                    "AND NOT EXISTS (SELECT 1 FROM context_tombstones t WHERE t.session_id=e.session_id) "
                    "GROUP BY origin",
                    (harness, parser),
                ).fetchall()
            )
            harnesses.append(
                {
                    "harness": harness,
                    "parser_version": parser,
                    "attempt_state": "no_attempt_recorded"
                    if attempt is None
                    else "incomplete_attempt"
                    if attempt[0] == "started"
                    else attempt[0],
                    "latest_attempt": dict(zip(keys, attempt, strict=True))
                    if attempt
                    else None,
                    "sessions_needing_native_backfill": legacy,
                    "native_records": native[0],
                    "native_sessions": native[1],
                    "latest_source_recorded_at": native[2],
                    "latest_local_capture_at": native[3],
                    "origins": origins,
                }
            )
        return {
            "status": "available",
            "scope": "operator_counts_only",
            "hook_liveness": "not_established",
            "archive_completeness": "not_established",
            "harnesses": harnesses,
        }
    finally:
        if owned:
            conn.rollback()
