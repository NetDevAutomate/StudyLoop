"""Clean-start rebuild: a NEW sessions.db holding only real conversations.

Owner decision 2026-09-12 ("clean start now, archive cold, decide deletion
later — not today"): the live database is never modified. A fresh, migrated
destination is created and rows are copied INTO it through a filter; the
source is attached read-only and detached untouched. Archiving the old file is
a separate, explicit step (see :func:`archive_source`).

The filter ("policy C" in the manifest the owner reviewed):

* a session is kept when its ``source`` is one of the six supported harnesses
  AND at least one of its messages is ``human`` (a person typed it);
* within a kept session, a message is kept when its kind is in
  :data:`~agent_session_tools.corpus.LEARNER_KINDS` (``human`` or ``prose``).

Every table in the source schema must be classified into exactly one of the
sets below or the rebuild refuses to run — a table nobody thought about is
schema drift, not something to copy blindly (see the closure-completeness
procedure this follows). After the copy, ``PRAGMA foreign_key_check`` must be
empty and the FTS index must have exactly one row per message with content.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from agent_session_tools.corpus import (
    KIND_HUMAN,
    build_message_kind_sql,
    learner_kinds_sql,
)

logger = logging.getLogger(__name__)

#: The release harness set (exporter registry keys map to these source labels).
SUPPORTED_SOURCES: Final[frozenset[str]] = frozenset(
    {"claude_code", "kiro_cli", "codex", "opencode", "pi", "grok"}
)

# ── Table classification ──────────────────────────────────────────────────────
# Each set names WHY a table is handled the way it is. Membership is asserted
# exhaustive against the live schema at run time; an unknown table raises.

#: Rows filtered by the keep-set (sessions) or keep-set + kind (messages).
FILTERED: Final[frozenset[str]] = frozenset({"sessions", "messages"})

#: Rows copied only when their ``message_id`` names a kept message.
FOLLOW_MESSAGE: Final[frozenset[str]] = frozenset(
    {"file_references", "scrub_log", "message_concepts"}
)

#: Rows copied only when their ``session_id`` names a kept session.
FOLLOW_SESSION: Final[frozenset[str]] = frozenset(
    {
        "session_learning_metadata",
        "session_notes",
        "session_tags",
        "study_sessions",
        "teach_back_scores",
        "context_record_owners",
        "context_observation_session_owners",
        "context_session_projects",
        "ontology_structural",
    }
)

#: ``context_evidence`` is session-keyed AND may be linked to a message via
#: ``context_native_message_sources``. An evidence row is kept when its session
#: is kept and it is not linked to a dropped message. The link table follows
#: the kept (message, evidence) pairs. Handled explicitly, not by a generic rule.
EVIDENCE: Final[frozenset[str]] = frozenset(
    {"context_evidence", "context_native_message_sources"}
)

#: Session FK is ``ON DELETE SET NULL``: copy every row, nulling the session
#: reference when the session was not kept. The learner record survives; its
#: pointer into a dropped conversation does not.
NULL_SESSION_IF_DROPPED: Final[frozenset[str]] = frozenset(
    {"parked_topics", "study_notes"}
)

#: Copied whole. Learner records and configuration with no session key, plus
#: capture-run history (a log of what ran, not of what it produced).
VERBATIM: Final[frozenset[str]] = frozenset(
    {
        "study_plans",
        "study_plan_checkpoints",
        "study_progress",
        "concepts",
        "concept_aliases",
        "concept_dependencies",
        "concept_relations",
        "knowledge_bridges",
        "practice_attempts",
        "card_reviews",
        "review_sessions",
        "context_board_columns",
        "context_capture_runs",
        "context_projects",
        "context_scope_audit",
        "context_tombstones",
        "context_retirements",
        "context_erasure_pending",
        "context_quarantine_discards",
        "context_annotation_retirements",
        "context_observation_retired_subjects",
        "context_observation_tombstones",
        "context_observation_supersedes",
        "context_observation_owners",
        "context_observation_sources",
        "context_observations",
        "context_record_observations",
        "context_record_study_links",
        "context_review_targets",
        "context_relations",
        "context_assertions",
        "context_citations",
        "context_concepts",
        "context_concept_events",
        "context_concept_clock",
        "context_concept_schema",
        # Replication ledger: peer/offer bookkeeping, copied so a peer that was
        # already accepted stays accepted. All were empty on the live db.
        "context_replica_peers",
        "context_replica_offers",
        "context_replica_basis_sets",
        "context_replica_row_bases",
        "context_replica_objects",
        "context_replica_denials",
        "context_replica_control_batches",
        "context_replica_permission_batches",
        "context_replica_permissions",
        "context_replica_superseded",
    }
)

#: Singletons the destination migration seeds for the NEW instance. Copying
#: the source value would collide with the seed or erase the new identity.
#: Same reasoning as tiering.compact_database.
INSTANCE_SINGLETONS: Final[frozenset[str]] = frozenset(
    {
        "context_access_state",
        "context_replica_content_state",
        "context_lifecycle_mode",
        "context_policy_state",
    }
)

#: Not copied; regenerated on the destination or by a later job.
#: - message_embeddings: `session-maint embed` re-encodes the kept rows and
#:   the vec sidecar must be rebuilt for the new file anyway.
#: - *_fts virtual tables: rebuilt by the insert triggers during copy.
#: - context_retention_origins: replication receipts, re-recorded per kept
#:   evidence row under the destination's own access-state instance.
#: - ontology_*: no writer exists on this branch (the PR #18 layer); the
#:   destination starts with the empty tables the migration creates.
REBUILT: Final[frozenset[str]] = frozenset(
    {
        "message_embeddings",
        "messages_fts",
        "context_evidence_fts",
        "context_concept_fts",
        "context_retention_origins",
        "ontology_build_state",
        "ontology_class",
        "ontology_property",
        "ontology_individual",
        "ontology_relation",
    }
)

_FTS_SHADOW_SUFFIXES: Final = ("_config", "_content", "_data", "_docsize", "_idx")


class UnclassifiedTableError(RuntimeError):
    """A source table belongs to none of the classification sets."""


@dataclass
class RebuildStats:
    dry_run: bool
    source: Path
    dest: Path | None
    sessions_kept: int = 0
    sessions_total: int = 0
    messages_kept: int = 0
    messages_total: int = 0
    tables_copied: dict[str, int] = field(default_factory=dict)
    tables_rebuilt: tuple[str, ...] = ()
    fk_violations: int = 0
    fts_rows: int = 0
    dest_size_mb: float = 0.0

    def render(self) -> str:
        head = "DRY RUN — nothing written" if self.dry_run else f"written: {self.dest}"
        lines = [
            f"clean-start rebuild ({head})",
            f"  source   : {self.source}",
            f"  sessions : keep {self.sessions_kept:,} of {self.sessions_total:,}",
            f"  messages : keep {self.messages_kept:,} of {self.messages_total:,}",
        ]
        if self.tables_copied:
            lines.append("  copied   :")
            for t, n in sorted(self.tables_copied.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {t:36s} {n:>9,}")
        if self.tables_rebuilt:
            lines.append(f"  rebuilt  : {', '.join(sorted(self.tables_rebuilt))}")
        if not self.dry_run:
            lines.append(f"  fk_check : {self.fk_violations} violation(s)")
            lines.append(f"  fts rows : {self.fts_rows:,}")
            lines.append(f"  size     : {self.dest_size_mb:.1f} MB")
        return "\n".join(lines)


# ── Schema exhaustiveness ─────────────────────────────────────────────────────


def _user_tables(conn: sqlite3.Connection, schema: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]


def _virtual_tables(conn: sqlite3.Connection, schema: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%'"
        )
    }


def classify_schema(conn: sqlite3.Connection, schema: str = "src") -> dict[str, str]:
    """Map every source table to its handling set; raise on any table left over.

    FTS shadow tables (``<virtual>_config`` etc.) are skipped ONLY when
    ``<virtual>`` is a declared virtual table; a plain table that merely ends
    in ``_data`` is still flagged.
    """
    virtual = _virtual_tables(conn, schema)
    sets = {
        "filtered": FILTERED,
        "follow_message": FOLLOW_MESSAGE,
        "follow_session": FOLLOW_SESSION,
        "evidence": EVIDENCE,
        "null_session_if_dropped": NULL_SESSION_IF_DROPPED,
        "verbatim": VERBATIM,
        "instance_singleton": INSTANCE_SINGLETONS,
        "rebuilt": REBUILT,
    }
    out: dict[str, str] = {}
    unknown: list[str] = []
    for table in _user_tables(conn, schema):
        if any(table == v + s for v in virtual for s in _FTS_SHADOW_SUFFIXES):
            out[table] = "fts_shadow"
            continue
        owners = [name for name, members in sets.items() if table in members]
        if len(owners) != 1:
            unknown.append(f"{table} -> {owners or 'UNCLASSIFIED'}")
            continue
        out[table] = owners[0]
    if unknown:
        raise UnclassifiedTableError(
            "source tables not in exactly one classification set: "
            + "; ".join(sorted(unknown))
        )
    return out


# ── Keep-set ──────────────────────────────────────────────────────────────────


def _build_keep_sets(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    """Create TEMP tables keep_sessions / keep_messages from the attached ``src``."""
    kind = build_message_kind_sql("m.role", "m.content")
    placeholders = ", ".join("?" for _ in SUPPORTED_SOURCES)
    conn.execute("DROP TABLE IF EXISTS temp.keep_sessions")
    conn.execute("DROP TABLE IF EXISTS temp.keep_messages")
    conn.execute(
        f"""
        CREATE TEMP TABLE keep_sessions AS
        SELECT s.id FROM src.sessions s
        WHERE s.source IN ({placeholders})
          AND EXISTS (
            SELECT 1 FROM src.messages m
            WHERE m.session_id = s.id AND ({kind}) = ?
          )
        """,
        (*sorted(SUPPORTED_SOURCES), KIND_HUMAN),
    )
    conn.execute(
        f"""
        CREATE TEMP TABLE keep_messages AS
        SELECT m.id FROM src.messages m
        WHERE m.session_id IN (SELECT id FROM temp.keep_sessions)
          AND {learner_kinds_sql(kind)}
        """
    )
    conn.execute("CREATE INDEX temp.ix_keep_sessions ON keep_sessions(id)")
    conn.execute("CREATE INDEX temp.ix_keep_messages ON keep_messages(id)")
    s_kept = conn.execute("SELECT COUNT(*) FROM temp.keep_sessions").fetchone()[0]
    s_total = conn.execute("SELECT COUNT(*) FROM src.sessions").fetchone()[0]
    m_kept = conn.execute("SELECT COUNT(*) FROM temp.keep_messages").fetchone()[0]
    m_total = conn.execute("SELECT COUNT(*) FROM src.messages").fetchone()[0]
    return s_kept, s_total, m_kept, m_total


# ── Copy ──────────────────────────────────────────────────────────────────────


def _cols(conn: sqlite3.Connection, table: str, schema: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _copy(
    conn: sqlite3.Connection,
    table: str,
    where: str = "",
    *,
    null_session: bool = False,
    ignore: bool = False,
) -> int:
    src_cols = _cols(conn, table, "src")
    dest_cols = set(_cols(conn, table, "main"))
    cols = [c for c in src_cols if c in dest_cols]
    if not cols:
        return 0
    select = []
    for c in cols:
        if null_session and c == "session_id":
            select.append(
                "CASE WHEN session_id IN (SELECT id FROM temp.keep_sessions) THEN session_id ELSE NULL END"
            )
        else:
            select.append(f'"{c}"')
    verb = "INSERT OR IGNORE" if ignore else "INSERT"
    q = (
        f'{verb} INTO main."{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
        f'SELECT {", ".join(select)} FROM src."{table}" {where}'
    )
    return conn.execute(q).rowcount


_IN_SESSIONS = "WHERE session_id IN (SELECT id FROM temp.keep_sessions)"
_IN_MESSAGES = "WHERE message_id IN (SELECT id FROM temp.keep_messages)"
_EVIDENCE_WHERE = (
    "WHERE session_id IN (SELECT id FROM temp.keep_sessions) "
    "AND id NOT IN ("
    "  SELECT evidence_id FROM src.context_native_message_sources"
    "  WHERE message_id NOT IN (SELECT id FROM temp.keep_messages))"
)
_NATIVE_LINK_WHERE = (
    "WHERE message_id IN (SELECT id FROM temp.keep_messages) "
    "AND evidence_id IN (SELECT id FROM main.context_evidence)"
)


def _copy_all(conn: sqlite3.Connection, classified: dict[str, str]) -> dict[str, int]:
    copied: dict[str, int] = {}

    def rec(table: str, n: int) -> None:
        if n:
            copied[table] = n
            logger.info("clean-rebuild: %s rows -> %s", n, table)

    # Parents before children. The destination has PRAGMA foreign_keys=OFF for
    # the copy and is checked afterwards, so order matters for correctness of
    # the check's meaning, not for the copy to succeed.
    rec(
        "sessions",
        _copy(conn, "sessions", "WHERE id IN (SELECT id FROM temp.keep_sessions)"),
    )
    rec(
        "messages",
        _copy(conn, "messages", "WHERE id IN (SELECT id FROM temp.keep_messages)"),
    )
    for t in sorted(FOLLOW_SESSION):
        if t in classified:
            rec(t, _copy(conn, t, _IN_SESSIONS))
    for t in sorted(FOLLOW_MESSAGE):
        if t in classified:
            rec(t, _copy(conn, t, _IN_MESSAGES))
    if "context_evidence" in classified:
        rec("context_evidence", _copy(conn, "context_evidence", _EVIDENCE_WHERE))
    if "context_native_message_sources" in classified:
        rec(
            "context_native_message_sources",
            _copy(
                conn, "context_native_message_sources", _NATIVE_LINK_WHERE, ignore=True
            ),
        )
    for t in sorted(NULL_SESSION_IF_DROPPED):
        if t in classified:
            rec(t, _copy(conn, t, null_session=True))
    # Verbatim: study_sessions is in FOLLOW_SESSION and is a parent of
    # parked_topics/study_notes via study_session_id (SET NULL) — a dropped
    # study session leaves a dangling pointer, so null those too.
    conn.execute(
        "UPDATE main.parked_topics SET study_session_id = NULL "
        "WHERE study_session_id IS NOT NULL "
        "AND study_session_id NOT IN (SELECT id FROM main.study_sessions)"
    )
    conn.execute(
        "UPDATE main.study_notes SET study_session_id = NULL "
        "WHERE study_session_id IS NOT NULL "
        "AND study_session_id NOT IN (SELECT id FROM main.study_sessions)"
    )
    for t in sorted(VERBATIM):
        if t in classified:
            rec(
                t,
                _copy(
                    conn,
                    t,
                    ignore=t in {"context_retirements", "context_erasure_pending"},
                ),
            )
    return copied


def _regenerate_retention_receipts(conn: sqlite3.Connection) -> int:
    """Re-record a native-capture receipt for every copied evidence row."""
    from agent_session_tools.replication import retention

    ids = [r[0] for r in conn.execute("SELECT id FROM main.context_evidence")]
    for evidence_id in ids:
        retention.record_native_evidence(conn, evidence_id)
    return len(ids)


# ── Public entry points ───────────────────────────────────────────────────────


def rebuild_clean(
    source: Path, dest: Path | None, *, dry_run: bool = True
) -> RebuildStats:
    """Build ``dest`` from ``source`` through the real-conversations filter.

    ``source`` is opened read-only (``mode=ro``, committed WAL included) and is
    never modified. With ``dry_run`` the keep-set is computed and reported and
    no destination is created.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")
    if not dry_run:
        if dest is None:
            raise ValueError("dest is required unless dry_run")
        if dest.exists():
            raise FileExistsError(
                f"Destination already exists, refusing to overwrite: {dest}"
            )
        if dest.resolve() == source.resolve():
            raise ValueError("dest must differ from source")

    stats = RebuildStats(dry_run=dry_run, source=source, dest=dest)
    src_uri = source.resolve().as_uri() + "?mode=ro"

    if dry_run:
        # uri=True so the ?mode=ro ATTACH below is parsed as a URI, not a filename.
        conn = sqlite3.connect("file::memory:", uri=True)
        try:
            conn.execute("ATTACH DATABASE ? AS src", (src_uri,))
            classified = classify_schema(conn, "src")
            s_kept, s_total, m_kept, m_total = _build_keep_sets(conn)
            stats.sessions_kept, stats.sessions_total = s_kept, s_total
            stats.messages_kept, stats.messages_total = m_kept, m_total
            stats.tables_rebuilt = tuple(
                sorted(t for t in classified if classified[t] == "rebuilt")
            )
            # Preview the follow-set sizes without writing anything.
            preview = {
                "context_evidence": f"SELECT COUNT(*) FROM src.context_evidence {_EVIDENCE_WHERE}",
                "session_tags": f"SELECT COUNT(*) FROM src.session_tags {_IN_SESSIONS}",
                "file_references": f"SELECT COUNT(*) FROM src.file_references {_IN_MESSAGES}",
            }
            for t, q in preview.items():
                if t in classified:
                    n = conn.execute(q).fetchone()[0]
                    if n:
                        stats.tables_copied[t] = n
            stats.tables_copied["sessions"] = s_kept
            stats.tables_copied["messages"] = m_kept
        finally:
            conn.close()
        return stats

    assert dest is not None
    from agent_session_tools.export_sessions import init_db
    from agent_session_tools.tiering import ensure_leaf_dir, fts_integrity

    ensure_leaf_dir(dest.parent)
    init_db(str(dest)).close()
    conn = sqlite3.connect(f"file:{dest}", uri=True)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS src", (src_uri,))
        conn.execute("BEGIN")
        classified = classify_schema(conn, "src")
        s_kept, s_total, m_kept, m_total = _build_keep_sets(conn)
        stats.sessions_kept, stats.sessions_total = s_kept, s_total
        stats.messages_kept, stats.messages_total = m_kept, m_total
        # The destination migration seeds this singleton; keep the source's
        # applied policy instead (same as compact_database).
        if "context_policy_state" in classified:
            conn.execute("DELETE FROM main.context_policy_state")
            stats.tables_copied["context_policy_state"] = _copy(
                conn, "context_policy_state"
            )
        stats.tables_copied.update(_copy_all(conn, classified))
        receipts = _regenerate_retention_receipts(conn)
        if receipts:
            stats.tables_copied["context_retention_origins (regenerated)"] = receipts
        conn.execute("COMMIT")
        conn.execute("DETACH DATABASE src")

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        stats.fk_violations = len(violations)
        if violations:
            by_pair: dict[tuple[str, str], int] = {}
            for table, _rowid, parent, _fkid in violations:
                by_pair[(table, parent)] = by_pair.get((table, parent), 0) + 1
            detail = ", ".join(
                f"{t}->{p}: {n}" for (t, p), n in sorted(by_pair.items())
            )
            raise RuntimeError(f"foreign_key_check failed after rebuild: {detail}")
        fts = fts_integrity(conn)
        stats.fts_rows = fts.fts_rows
        if not fts.healthy:
            raise RuntimeError(
                f"FTS invariant violated: {fts.fts_rows} index rows for "
                f"{fts.messages_with_content} messages with content"
            )
        stats.tables_rebuilt = tuple(
            sorted(t for t in classified if classified[t] == "rebuilt")
        )
        conn.execute("VACUUM")
    finally:
        conn.close()
    stats.dest_size_mb = dest.stat().st_size / 1024 / 1024
    return stats


def archive_source(
    source: Path, archive_dir: Path, *, review_after: str = "2026-12-12"
) -> Path:
    """Move ``source`` (and its WAL/SHM if present) into ``archive_dir``, cold.

    Moves, never deletes. Writes a README beside the file naming the owner's
    review date so the deletion decision is scheduled, not forgotten. The
    caller is responsible for ensuring nothing is writing to ``source``.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    target = archive_dir / f"{source.stem}-archived-{stamp}{source.suffix}"
    if target.exists():
        raise FileExistsError(f"Archive target already exists: {target}")
    shutil.move(str(source), str(target))
    for suffix in ("-wal", "-shm"):
        side = source.with_name(source.name + suffix)
        if side.exists():
            shutil.move(str(side), str(target.with_name(target.name + suffix)))
    readme = archive_dir / "README.md"
    readme.write_text(
        "# StudyLoop session archive\n\n"
        f"`{target.name}` is the pre-clean-start `sessions.db`, moved here on {stamp}.\n"
        "Nothing reads it. It is the only copy of harness history whose native\n"
        "transcripts have since been rotated (Claude Code before 2026-07-10).\n\n"
        f"Owner decision 2026-09-12: keep cold; review for deletion on **{review_after}**.\n"
        "To reclaim disk before then, compress rather than delete: `zstd -19 <file>`.\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "EVIDENCE",
    "FILTERED",
    "FOLLOW_MESSAGE",
    "FOLLOW_SESSION",
    "INSTANCE_SINGLETONS",
    "NULL_SESSION_IF_DROPPED",
    "REBUILT",
    "SUPPORTED_SOURCES",
    "VERBATIM",
    "RebuildStats",
    "UnclassifiedTableError",
    "archive_source",
    "classify_schema",
    "rebuild_clean",
]
