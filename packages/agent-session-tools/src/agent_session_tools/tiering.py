"""Database tiering: hot (local) / full (external) session store management.

The tiering model:

- **Hot DB** (``~/.config/studyloop/sessions.db``) — the live database every
  code-harness exporter writes to. Always local so session exports never
  depend on an external volume being mounted. May be pruned to the last
  N days on machines with small drives.
- **Full DB** (``database.full_db_path`` in config.yaml, e.g. on an external
  volume) — the complete, append-mostly history: a single-writer mirror of
  the hot DB's whole context tier, bound to one canonical instance and
  maintained by :func:`sync_to_full` (copied and verified by the table-role
  registry in :mod:`agent_session_tools.tiering_registry`).
- **Snapshots** (``database.backup_dir``) — periodic point-in-time copies of
  the full DB with retention, protecting against corruption that an
  incremental sync would faithfully propagate.

Safety invariants:

- :func:`prune_hot` verifies retained messages and, for modern schemas, a complete
  context/learner snapshot before eviction. Incomplete coverage retains hot data.
- Directory creation only ever creates the *leaf* directory. If the parent
  does not exist (external volume unmounted), the operation is refused rather
  than silently writing to a phantom mountpoint path.
- FTS consistency is an explicit, checkable invariant:
  ``count(messages_fts) == count(messages WHERE content IS NOT NULL)``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_session_tools.config_loader import (
    get_config_dir,
    get_db_path,
    load_config,
)

logger = logging.getLogger(__name__)

# Tables whose rows belong to a session/message and must follow it on
# sync/prune. FK discovery below augments this list at runtime, so tables
# added later by either package are still cleaned up if they declare FKs.
_SESSION_CHILD_TABLES = ("session_learning_metadata",)
_MESSAGE_CHILD_TABLES = ("message_embeddings", "message_concepts")

# What is synced into the full DB is the table-role registry
# (``tiering_registry``). Embeddings are derived data and deliberately NOT
# synced — they are regenerated locally by ``session-maint embed`` (migration
# 48; the derived vector index is a sidecar).

# Derived tables that must NOT take part in the whole-context retention proof:
# they are never synced to the full tier, so requiring them there would make
# ``prune_hot`` silently stop evicting the moment a vector exists in the hot DB.
_DERIVED_TABLES = frozenset({"message_embeddings"})


_MARKER_FILE = ".last_full_sync"
_LOCK_FILE = ".full_sync.lock"
_LOCK_STALE_SECONDS = 3600


# ---------------------------------------------------------------------------
# Stats dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FtsIntegrity:
    """Result of the FTS index invariant checks.

    ``drift``/``fts_rows``/``messages_with_content`` describe ``messages_fts``
    (unchanged meaning). ``evidence_*`` describe ``context_evidence_fts``, an
    external-content index whose own cardinality is its ``_docsize`` row count;
    both are zero on a database without that index. ``healthy`` needs both.
    """

    messages_with_content: int
    fts_rows: int
    evidence_rows: int = 0
    evidence_fts_rows: int = 0

    @property
    def drift(self) -> int:
        return self.fts_rows - self.messages_with_content

    @property
    def evidence_drift(self) -> int:
        return self.evidence_fts_rows - self.evidence_rows

    @property
    def healthy(self) -> bool:
        return self.drift == 0 and self.evidence_drift == 0


@dataclass
class CompactStats:
    """Result of compacting a bloated DB into a clean one."""

    tables_copied: dict[str, int] = field(default_factory=dict)
    source_size_mb: float = 0.0
    dest_size_mb: float = 0.0
    fts: FtsIntegrity | None = None


@dataclass
class SyncStats:
    """Result of an incremental hot -> full sync."""

    sessions_synced: int = 0
    messages_synced: int = 0
    file_references_synced: int = 0
    sessions_total_full: int = 0
    #: Rows written per table (inserted or updated) by this run.
    rows_copied: dict[str, int] = field(default_factory=dict)
    #: True when this run bound an empty full tier to hot's instance.
    bound: bool = False
    #: True when the receipt proved nothing changed and no write ran.
    fast_path: bool = False


# ---------------------------------------------------------------------------
# Mirror refusals
# ---------------------------------------------------------------------------

_REFUSAL_FIXES = {
    "distinct_paths": (
        "database.path and database.full_db_path must name two different files"
    ),
    "noncanonical_override": (
        "sync-full mirrors the configured database.path into database.full_db_path; "
        "run it without --db, or point the config at the database you meant"
    ),
    "schema_mismatch": (
        "run any session-export (it migrates the hot database), or upgrade this "
        "installation if the full database is newer, then run sync-full again"
    ),
    "peer_ledger_present": (
        "this database has taken part in structured replication; the SQL mirror "
        "does not carry it -- use the structured sync coordinator instead"
    ),
    "unbound_full": (
        "the full database was not written by this mirror: move it aside (keep it "
        "as a backup) and run sync-full again to create a bound mirror"
    ),
    "instance_mismatch": (
        "the full database belongs to another instance (hot was rebuilt or "
        "compacted, or the file is another machine's): point database.full_db_path "
        "at a new file, or move the old full database aside"
    ),
    "unclassified_table": (
        "this build does not know that table, so it cannot mirror or verify it; "
        "upgrade agent-session-tools -- nothing was copied"
    ),
    "controls_unstable": (
        "another process changed permanent deletions during the sync; run sync-full again"
    ),
    "controls_changed": (
        "a permanent deletion arrived between reconciliation and the copy; "
        "run sync-full again -- nothing was copied"
    ),
    "immutable_collision": (
        "the full database holds a different version of an immutable row; nothing "
        "was copied -- inspect that row before syncing (another tool wrote the full tier)"
    ),
    "orphan_row": (
        "the hot database holds a row whose parent is missing "
        "(PRAGMA foreign_key_check); repair it before syncing -- nothing was copied"
    ),
    "constraint_violation": (
        "a row could not be mirrored without breaking a uniqueness rule in the "
        "full database; nothing was copied"
    ),
    "full_store_unavailable": "mount the volume holding the full database and retry",
    "managed_store_busy_or_unavailable": (
        "another process holds a database write lock; sync-full will retry on the "
        "next trigger, or run it again"
    ),
}


class TieringRefused(ValueError):
    """The hot -> full mirror refused; ``reason`` is a stable code, ``fix`` the remedy.

    A ``ValueError`` so the ``sync-full`` and ``prune`` handlers render it; it is
    deliberately not :class:`replication.legacy.LegacySyncRefused`, which keeps
    meaning "this needs the structured protocol" for peer and legacy paths.
    """

    def __init__(
        self,
        reason: str,
        detail: str = "",
        *,
        table: str | None = None,
        key: object = None,
    ) -> None:
        self.reason = reason
        self.table = table
        self.key = key
        self.fix = _REFUSAL_FIXES.get(reason, "run sync-full again")
        message = f"sync-full refused ({reason})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


@dataclass
class PruneStats:
    """Result of pruning the hot DB."""

    candidates: int = 0
    verified: int = 0
    skipped_unverified: int = 0
    skipped_anchored: int = 0
    # Sessions with no updated_at, created_at or message timestamp: their age
    # is unknown, so they are never "older than N days" (F-AST-06 rule).
    skipped_undated: int = 0
    sessions_deleted: int = 0
    messages_deleted: int = 0
    reclaimed_mb: float = 0.0
    dry_run: bool = False
    skipped_ids: list[str] = field(default_factory=list)
    anchored_ids: list[str] = field(default_factory=list)


@dataclass
class RefocusStats:
    """Result of a focus-change data movement (pull then prune)."""

    topics: list[str] = field(default_factory=list)
    pulled_sessions: int = 0
    pulled_messages: int = 0
    kept_in_focus: int = 0
    prune: PruneStats | None = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def get_full_db_path(config: dict[str, Any] | None = None) -> Path | None:
    """Return the configured full-DB path, or None when tiering is disabled."""
    if config is None:
        config = load_config()
    raw = str(config.get("database", {}).get("full_db_path", "") or "").strip()
    if not raw:
        return None
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def ensure_leaf_dir(path: Path) -> None:
    """Create *only* the final directory component of ``path``, owner-only.

    Refuses when the parent is missing. This is the mount-safety guard: on
    macOS an unmounted external volume means ``/Volumes/<name>`` does not
    exist, and a recursive mkdir would silently create a real directory on
    the boot volume that later shadows the mount.

    The leaf holds copies of the 0600 record (the full tier, its snapshots,
    a compact destination), so it is created 0700. An existing directory
    keeps its mode; ``session-maint fix-perms`` tightens those on request.
    """
    if path.exists():
        return
    if not path.parent.exists():
        raise FileNotFoundError(
            f"Parent directory missing: {path.parent} — is the volume mounted? "
            "Create the directory structure once manually, then retry."
        )
    path.mkdir(mode=0o700)


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, table: str, schema: str = "main") -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


# Learner tables that hang off a conversation. Eviction sweeps them by
# session_id, owner binding and study_session_id (lifecycle.selected_records),
# so the session they anchor must stay in hot for invariant 3 of
# docs/session-db-tiering.md ("learning tables are never pruned") to hold.
_LEARNER_ANCHOR_TABLES = (
    "study_sessions",
    "teach_back_scores",
    "parked_topics",
    "study_notes",
    "practice_attempts",
    "knowledge_bridges",
)


def _anchored_session_ids(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    """Sessions whose eviction would delete a learner record.

    Discovery follows the same three routes ``purge_session`` uses to select
    rows, so a session is anchored exactly when eviction would touch a learner
    table: a direct ``session_id`` column, a ``study_session_id`` that resolves
    to a bound study session, or a ``context_record_owners`` binding.
    """
    anchored: set[str] = set()
    has_study = _table_exists(conn, "study_sessions", schema)
    for table in _LEARNER_ANCHOR_TABLES:
        if not _table_exists(conn, table, schema):
            continue
        columns = {r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")}
        if "session_id" in columns:
            anchored.update(
                r[0]
                for r in conn.execute(
                    f"SELECT DISTINCT session_id FROM {schema}.{table} "
                    "WHERE session_id IS NOT NULL"
                )
            )
        if "study_session_id" in columns and has_study:
            anchored.update(
                r[0]
                for r in conn.execute(
                    f"SELECT DISTINCT s.session_id FROM {schema}.{table} r "
                    f"JOIN {schema}.study_sessions s ON s.id = r.study_session_id "
                    "WHERE s.session_id IS NOT NULL"
                )
            )
    if _table_exists(conn, "context_record_owners", schema):
        placeholders = ",".join("?" * len(_LEARNER_ANCHOR_TABLES))
        anchored.update(
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT session_id FROM {schema}.context_record_owners "
                f"WHERE session_id IS NOT NULL AND table_name IN ({placeholders})",
                _LEARNER_ANCHOR_TABLES,
            )
        )
    return anchored


def _table_columns(
    conn: sqlite3.Connection, table: str, schema: str = "main"
) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _user_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    # PRAGMA table_list identifies virtual and shadow tables by type, so new
    # FTS indexes are rebuilt by their source triggers instead of copying their
    # internal pages into an already initialized destination. A name-prefix rule
    # handled only messages_fts and broke when context_evidence_fts was added.
    return [
        row[1]
        for row in conn.execute(f"PRAGMA {schema}.table_list")
        if row[0] == schema and row[2] == "table" and not row[1].startswith("sqlite_")
    ]


def _dependent_tables(conn: sqlite3.Connection, parent: str) -> list[tuple[str, str]]:
    """Return ``(table, fk_column)`` pairs for tables with a FK to ``parent``.

    Discovered dynamically so tables added by either package are handled,
    then unioned with the known child-table lists for tables that reference
    sessions/messages without a declared FK.
    """
    result: list[tuple[str, str]] = []
    for table in _user_tables(conn):
        if table in ("sessions", "messages", "messages_fts"):
            continue
        try:
            for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
                if fk[2] == parent:  # fk[2] = referenced table, fk[3] = from column
                    result.append((table, fk[3]))
        except sqlite3.OperationalError:
            continue
    known = _SESSION_CHILD_TABLES if parent == "sessions" else _MESSAGE_CHILD_TABLES
    key = "session_id" if parent == "sessions" else "message_id"
    for table in known:
        if _table_exists(conn, table) and (table, key) not in result:
            if key in _table_columns(conn, table):
                result.append((table, key))
    return result


def _copy_table(
    conn: sqlite3.Connection,
    table: str,
    src_schema: str,
    dest_schema: str = "main",
    where: str = "",
    replace: bool = False,
    ignore: bool = False,
) -> int:
    """Copy ``table`` rows using the column intersection of both schemas."""
    src_cols = _table_columns(conn, table, src_schema)
    dest_cols = _table_columns(conn, table, dest_schema)
    cols = [c for c in src_cols if c in dest_cols]
    if not cols:
        return 0
    col_list = ", ".join(cols)
    verb = (
        "INSERT OR REPLACE" if replace else "INSERT OR IGNORE" if ignore else "INSERT"
    )
    cur = conn.execute(
        f"{verb} INTO {dest_schema}.{table} ({col_list}) "
        f"SELECT {col_list} FROM {src_schema}.{table} {where}"
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# FTS integrity (the 45GB-bug guardrail)
# ---------------------------------------------------------------------------


def fts_integrity(conn: sqlite3.Connection) -> FtsIntegrity:
    """Check the FTS invariants: one index row per message with content, and one
    ``context_evidence_fts`` document per evidence row.

    A drifted index means the sync triggers were bypassed (bulk re-insert
    bug) or messages were deleted outside the triggers. Historical versions
    of the exporter re-indexed every message on every run, growing one DB
    to 45GB (586 duplicate index copies of 32MB of content).
    """
    messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE content IS NOT NULL"
    ).fetchone()[0]
    fts_rows = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    evidence = evidence_fts = 0
    if _table_exists(conn, "context_evidence_fts_docsize"):
        # External content: count(*) on the FTS table itself reads
        # context_evidence, so the index's own cardinality is its docsize rows.
        evidence = conn.execute("SELECT COUNT(*) FROM context_evidence").fetchone()[0]
        evidence_fts = conn.execute(
            "SELECT COUNT(*) FROM context_evidence_fts_docsize"
        ).fetchone()[0]
    return FtsIntegrity(
        messages_with_content=messages,
        fts_rows=fts_rows,
        evidence_rows=evidence,
        evidence_fts_rows=evidence_fts,
    )


def repair_fts(conn: sqlite3.Connection) -> FtsIntegrity:
    """Rebuild the FTS indexes from their source tables (idempotent).

    Note: FTS5's built-in ``('rebuild')`` command rebuilds the inverted index
    from the FTS table's *own* content store, so it preserves duplicate rows.
    A drifted standalone FTS table must be cleared and repopulated from the
    source of truth instead. ``context_evidence_fts`` is external-content
    (its content store *is* ``context_evidence``), so ``'rebuild'`` is the
    correct repair there -- the same one ``lifecycle.compact`` runs.
    """
    with conn:
        conn.execute("DELETE FROM messages_fts")
        conn.execute(
            """
            INSERT INTO messages_fts(rowid, content, session_id, role)
            SELECT rowid, content, session_id, role
            FROM messages WHERE content IS NOT NULL
            """
        )
        if _table_exists(conn, "context_evidence_fts"):
            conn.execute(
                "INSERT INTO context_evidence_fts(context_evidence_fts) VALUES ('rebuild')"
            )
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('optimize')")
    return fts_integrity(conn)


# ---------------------------------------------------------------------------
# Compact (rescue a bloated DB into a clean one)
# ---------------------------------------------------------------------------


def compact_database(source: Path, dest: Path) -> CompactStats:
    """Copy all real data from ``source`` into a fresh, migrated DB at ``dest``.

    The FTS index is rebuilt exactly once via the insert triggers on the
    destination — duplicated index rows in the source are left behind.
    ``source`` is opened read-only, including its committed WAL, and never modified.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")
    if dest.exists():
        raise FileExistsError(
            f"Destination already exists, refusing to overwrite: {dest}"
        )

    from agent_session_tools.export_sessions import init_db

    ensure_leaf_dir(dest.parent)
    # URI mode=ro includes committed WAL records; immutable=1 would silently
    # ignore a live writer's journal and lose recently captured conversations.
    init_db(str(dest)).close()
    conn = sqlite3.connect(f"file:{dest}", uri=True)
    stats = CompactStats(source_size_mb=source.stat().st_size / 1024 / 1024)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "ATTACH DATABASE ? AS src", (source.resolve().as_uri() + "?mode=ro",)
        )
        # Hold a source read snapshot through introspection and every table copy.
        conn.execute("BEGIN")

        src_tables = set(_user_tables(conn, "src")) - {"messages_fts"}
        dest_tables = set(_user_tables(conn, "main")) - {"messages_fts"}
        common = src_tables & dest_tables
        # A compacted database is a new local instance. Retain its initialized
        # access generation; copying the source singleton would both collide
        # with that row and erase the replacement identity observed by readers.
        common.discard("context_access_state")
        # Body generations belong to the new instance as well. Destination
        # inserts advance its seeded counter; the source value is not portable.
        common.discard("context_replica_content_state")
        common.discard("context_lifecycle_mode")
        # Dependency order: parents before children; messages last of the
        # core pair so session FKs resolve. Everything else after.
        first = ("context_tombstones", "sessions", "messages")
        ordered = [t for t in first if t in common]
        ordered += sorted(common - set(first))

        with conn:
            if "context_policy_state" in common:
                # The destination migration seeds a singleton. Preserve the
                # source's applied policy instead of colliding with that seed.
                conn.execute("DELETE FROM context_policy_state")
            for table in ordered:
                copied = _copy_table(
                    conn,
                    table,
                    "src",
                    ignore=table
                    in {
                        "context_retirements",
                        "context_erasure_pending",
                    },
                )
                if copied:
                    stats.tables_copied[table] = copied
                    logger.info("compact: copied %s rows into %s", copied, table)

        conn.execute("DETACH DATABASE src")
        stats.fts = fts_integrity(conn)
        conn.execute("VACUUM")
    finally:
        conn.close()

    stats.dest_size_mb = dest.stat().st_size / 1024 / 1024
    return stats


# ---------------------------------------------------------------------------
# Incremental sync (hot -> full): preflight and binding
# ---------------------------------------------------------------------------


@dataclass
class _MirrorPlan:
    """What the read-only preflight established about the hot/full pair."""

    instance: str
    revision: int
    full_exists: bool
    bound: bool
    receipt: int | None


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _same_file(a: Path, b: Path) -> bool:
    if a.resolve() == b.resolve():
        return True
    return a.exists() and b.exists() and a.samefile(b)


def _refuse_peer_ledger(conn: sqlite3.Connection, schema: str, label: str) -> None:
    from .tiering_registry import PEER_LEDGER

    tables = set(_user_tables(conn, schema))
    holding = [
        entry.name
        for entry in PEER_LEDGER
        if entry.name in tables
        and conn.execute(f"SELECT 1 FROM {schema}.{entry.name} LIMIT 1").fetchone()
    ]
    if holding:
        raise TieringRefused(
            "peer_ledger_present",
            f"the {label} database holds structured-replication rows in "
            + ", ".join(holding),
        )


def _populated(conn: sqlite3.Connection, schema: str) -> list[str]:
    """Payload or control tables in ``schema`` that hold any row."""
    from .tiering_registry import CONTROL, PAYLOAD

    tables = set(_user_tables(conn, schema))
    return [
        entry.name
        for entry in (*PAYLOAD, *CONTROL)
        if entry.name in tables
        and conn.execute(f'SELECT 1 FROM {schema}."{entry.name}" LIMIT 1').fetchone()
    ]


def _mirror_preflight(
    hot: Path, full: Path, configured_hot: Path, configured_full: Path
) -> _MirrorPlan:
    """Read-only checks before anything in the full tier is migrated or written."""
    from .migrations import CURRENT_VERSION
    from .tiering_registry import MIRROR_TABLE, UnclassifiedTable, classify_database

    if _same_file(hot, full):
        raise TieringRefused("distinct_paths", f"both name {hot.resolve()}")
    if not _same_file(hot, configured_hot) or not _same_file(full, configured_full):
        raise TieringRefused(
            "noncanonical_override",
            f"asked to mirror {hot} into {full}; configured pair is "
            f"{configured_hot} -> {configured_full}",
        )
    with closing(_open_ro(hot)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != CURRENT_VERSION:
            raise TieringRefused(
                "schema_mismatch",
                f"the hot database is at schema {version}; this build mirrors "
                f"schema {CURRENT_VERSION}",
            )
        try:
            classify_database(conn)
        except UnclassifiedTable as exc:
            raise TieringRefused(
                "unclassified_table", str(exc), table=exc.table
            ) from exc
        _refuse_peer_ledger(conn, "main", "hot")
        instance = conn.execute(
            "SELECT instance FROM context_access_state WHERE id=1"
        ).fetchone()[0]
        revision = conn.execute(
            "SELECT revision FROM context_replica_content_state WHERE id=1"
        ).fetchone()[0]
    plan = _MirrorPlan(instance, revision, False, False, None)
    if not full.exists() or full.stat().st_size == 0:
        return plan
    plan.full_exists = True
    with closing(_open_ro(full)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > CURRENT_VERSION:
            raise TieringRefused(
                "schema_mismatch",
                f"the full database is at schema {version}, newer than this build "
                f"({CURRENT_VERSION})",
            )
        _refuse_peer_ledger(conn, "main", "full")
        if _table_exists(conn, MIRROR_TABLE):
            row = conn.execute(
                f"SELECT canonical_instance, last_source_revision FROM {MIRROR_TABLE} "
                "WHERE id=1"
            ).fetchone()
            if row is not None:
                if row[0] != instance:
                    raise TieringRefused(
                        "instance_mismatch",
                        f"the full database is bound to instance {row[0]}; the hot "
                        f"database is instance {instance}",
                    )
                plan.bound, plan.receipt = True, row[1]
                return plan
        holding = _populated(conn, "main")
        if holding:
            raise TieringRefused(
                "unbound_full",
                f"{full} holds rows (in {', '.join(holding[:5])}"
                + (", ..." if len(holding) > 5 else "")
                + ") and no mirror binding",
            )
    return plan


def _bind_full(conn: sqlite3.Connection, plan: _MirrorPlan) -> bool:
    """Create/verify the binding inside the content transaction; True when bound now.

    The table is created here, in the full tier only, rather than by a migration:
    migrations are tier-agnostic (``init_db`` runs the same chain on hot and full),
    and a hot carrying an empty binding table would mean nothing.
    """
    from .tiering_registry import MIRROR_TABLE

    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS main.{MIRROR_TABLE} (
            id INTEGER PRIMARY KEY CHECK(id=1),
            canonical_instance TEXT NOT NULL,
            bound_at TEXT NOT NULL,
            last_source_revision INTEGER
        )"""
    )
    row = conn.execute(
        f"SELECT canonical_instance FROM main.{MIRROR_TABLE} WHERE id=1"
    ).fetchone()
    if row is not None:
        if row[0] != plan.instance:
            raise TieringRefused(
                "instance_mismatch",
                f"the full database is bound to instance {row[0]}",
            )
        return False
    holding = _populated(conn, "main")
    if holding:
        raise TieringRefused(
            "unbound_full", f"rows appeared in {', '.join(holding[:5])} during sync"
        )
    conn.execute(
        f"INSERT INTO main.{MIRROR_TABLE} VALUES (1, ?, ?, NULL)",
        (plan.instance, datetime.now(UTC).isoformat()),
    )
    return True


# ---------------------------------------------------------------------------
# Incremental sync (hot -> full)
# ---------------------------------------------------------------------------


def sync_to_full(
    hot: Path | None = None,
    full: Path | None = None,
    config: dict[str, Any] | None = None,
) -> SyncStats:
    """Mirror the hot DB's whole context tier into the bound full DB (idempotent).

    The full tier is a single-writer mirror bound to one canonical instance
    (ADR-0016 amendment; council pass 7). In order:

    1. ``check_config`` -- scoped/peer configurations still need the structured
       protocol (``LegacySyncRefused``); then a read-only preflight
       (:func:`_mirror_preflight`) before anything in full is migrated.
    2. Fast path: full's receipt equals hot's content revision, the permanent
       controls are equal and the tables the revision does not track hold
       nothing new -- no write transaction is opened on either file.
    3. Controls: ``managed_history.reconcile_full_controls`` converges the
       permanent controls canonical-first, without compacting.
    4. Content, one transaction on full with hot attached read-only and
       foreign keys on: re-check the controls, re-apply retirements to full,
       then copy by the table-role registry (``tiering_registry``) -- sessions
       upserted, changed sessions' messages/file references replaced,
       immutable rows inserted if absent (a differing overlapping key refuses),
       mutable rows upserted where they differ. Never ``INSERT OR REPLACE``.
       The receipt is written in the same transaction.

    Deletions reach full only through the controls phase; a session evicted
    from hot by ``prune_hot`` stays in full by design. Instance-local state
    (identity, generations, policy, capture runs, origin labels, peer ledgers)
    is never copied. Refusals raise :class:`TieringRefused`.
    """
    from .context import managed_history
    from .context.scope import ScopeError
    from .replication.legacy import check_config

    cfg = config or load_config()
    configured_hot = get_db_path(cfg)
    configured_full = get_full_db_path(cfg)
    hot = hot or configured_hot
    full = full or configured_full
    if full is None or configured_full is None:
        raise ValueError(
            "database.full_db_path is not configured — set it in config.yaml "
            "to enable tiering"
        )
    if not hot.exists():
        raise FileNotFoundError(f"Hot database not found: {hot}")

    # The structured protocol still owns every scoped/peer configuration.
    check_config(cfg)
    plan = _mirror_preflight(hot, full, configured_hot, configured_full)
    if plan.bound and _nothing_changed(hot, full, plan):
        with closing(_open_ro(full)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        logger.info("sync_to_full: nothing changed (receipt %s)", plan.receipt)
        return SyncStats(sessions_total_full=total, fast_path=True)

    from agent_session_tools.export_sessions import init_db

    ensure_leaf_dir(full.parent)
    init_db(str(full)).close()
    _check_mirror_schemas(hot, full)

    try:
        controls = managed_history.reconcile_full_controls(hot=hot, config=cfg)
    except ScopeError as exc:
        raise TieringRefused("controls_unstable", str(exc)) from exc
    if not controls.get("controls_stable"):
        raise TieringRefused(
            str(controls.get("reason") or "controls_unstable"),
            "permanent controls could not be reconciled with the full database",
        )

    stats = _mirror_copy(hot, full, plan)
    logger.info(
        "sync_to_full: %s session(s) changed, %s row(s) written, full DB holds %s sessions",
        stats.sessions_synced,
        sum(stats.rows_copied.values()),
        stats.sessions_total_full,
    )
    return stats


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _missing_sql(
    table: str,
    cols: list[str],
    key: tuple[str, ...],
    *,
    keys_only: bool,
    select: list[str] | None = None,
    source: str = "hot",
    archive: str = "main",
) -> str:
    """Hot rows of ``table`` absent from full: by key, or by whole-row equality.

    A correlated ``NOT EXISTS`` probe on full's primary key (council pass 7, A2):
    ``EXCEPT`` plans as a merge scanning both sides -- the whole archive on
    every run -- while the anti-join searches full's key index once per hot row.
    ``select`` narrows the returned columns (default: every column);
    ``source``/``archive`` name the hot and full schemas on this connection.
    """
    match = cols if not keys_only else list(key)
    where = " AND ".join(f"x.{_q(c)} IS h.{_q(c)}" for c in match)
    selected = ", ".join(f"h.{_q(c)}" for c in (select or cols))
    return (
        f"SELECT {selected} FROM {source}.{_q(table)} h WHERE NOT EXISTS "
        f"(SELECT 1 FROM {archive}.{_q(table)} x WHERE {where})"
    )


def _upsert_sql(table: str, cols: list[str], key: tuple[str, ...]) -> str:
    """Insert new rows and update rows whose columns differ; never a delete."""
    non_key = [c for c in cols if c not in key]
    target = ", ".join(_q(c) for c in key)
    if non_key:
        assignments = ", ".join(f"{_q(c)}=excluded.{_q(c)}" for c in non_key)
        differs = " OR ".join(
            f"{_q(table)}.{_q(c)} IS NOT excluded.{_q(c)}" for c in non_key
        )
        conflict = f"ON CONFLICT({target}) DO UPDATE SET {assignments} WHERE {differs}"
    else:
        conflict = f"ON CONFLICT({target}) DO NOTHING"
    return (
        f"INSERT INTO main.{_q(table)} ({', '.join(_q(c) for c in cols)}) "
        + _missing_sql(table, cols, key, keys_only=False)
        + f" {conflict}"
    )


def _untracked_payload(conn: sqlite3.Connection, schema: str) -> list[str]:
    """Payload tables whose changes do not advance hot's content revision.

    Migration 46 installs ``replica_content_<table>_{insert,update,delete}``
    triggers on a frozen list; ``scrub_log``, ``message_concepts``,
    ``context_projects``, ``context_board_columns`` and the concept graph are
    outside it, so the receipt alone cannot prove they are unchanged.
    """
    from .tiering_registry import PAYLOAD

    triggers = {
        row[0]
        for row in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='trigger' "
            "AND name LIKE 'replica_content_%'"
        )
    }
    return [
        entry.name
        for entry in PAYLOAD
        if not all(
            f"replica_content_{entry.name}_{event}" in triggers
            for event in ("insert", "update", "delete")
        )
    ]


def _controls_differ(
    conn: sqlite3.Connection, source: str = "hot", archive: str = "main"
) -> str | None:
    """The first control table whose identities differ between hot and full."""
    from .tiering_registry import CONTROL

    for entry in CONTROL:
        match = " AND ".join(f"x.{_q(c)} IS h.{_q(c)}" for c in entry.key)
        for left, right in ((source, archive), (archive, source)):
            if conn.execute(
                f"SELECT 1 FROM {left}.{_q(entry.name)} h WHERE NOT EXISTS "
                f"(SELECT 1 FROM {right}.{_q(entry.name)} x WHERE {match}) LIMIT 1"
            ).fetchone():
                return entry.name
    return None


def _nothing_changed(hot: Path, full: Path, plan: _MirrorPlan) -> bool:
    """The O(1) receipt check plus the untracked tables, read-only on both files."""
    from .migrations import CURRENT_VERSION

    if plan.receipt is None or plan.receipt != plan.revision:
        return False
    with closing(_open_ro(full)) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != CURRENT_VERSION:
            return False
        conn.execute("ATTACH DATABASE ? AS hot", (hot.resolve().as_uri() + "?mode=ro",))
        conn.execute("BEGIN")  # one read snapshot over both files
        try:
            revision = conn.execute(
                "SELECT revision FROM hot.context_replica_content_state WHERE id=1"
            ).fetchone()[0]
            if revision != plan.receipt or _controls_differ(conn):
                return False
            from .tiering_registry import REGISTRY, columns

            for table in _untracked_payload(conn, "hot"):
                entry = REGISTRY[table]
                sql = _missing_sql(
                    table, columns(conn, table, "hot"), entry.key, keys_only=False
                )
                if conn.execute(sql + " LIMIT 1").fetchone():
                    return False
            return True
        finally:
            conn.rollback()


def _check_mirror_schemas(hot: Path, full: Path) -> None:
    """Exact registered column sets on both sides -- never a column intersection."""
    from .tiering_registry import CONTROL, PAYLOAD, columns

    with closing(_open_ro(full)) as conn:
        conn.execute("ATTACH DATABASE ? AS hot", (hot.resolve().as_uri() + "?mode=ro",))
        versions = [
            conn.execute(f"PRAGMA {schema}.user_version").fetchone()[0]
            for schema in ("hot", "main")
        ]
        if versions[0] != versions[1]:
            raise TieringRefused(
                "schema_mismatch",
                f"hot is at schema {versions[0]}, full at {versions[1]} after migration",
            )
        for entry in (*PAYLOAD, *CONTROL):
            ours, theirs = (
                columns(conn, entry.name, "hot"),
                columns(conn, entry.name, "main"),
            )
            if ours != theirs or not ours:
                raise TieringRefused(
                    "schema_mismatch",
                    f"{entry.name} has columns {ours} in hot and {theirs} in full",
                    table=entry.name,
                )


def _mirror_copy(hot: Path, full: Path, plan: _MirrorPlan) -> SyncStats:
    """The content transaction: one ``BEGIN IMMEDIATE`` on full, hot read-only."""
    from .context.lifecycle import reconcile_local_retirements
    from .replication.legacy import check_config
    from .tiering_registry import MIRROR_TABLE

    stats = SyncStats()
    conn = sqlite3.connect(
        full.resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5
    )
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        # Read-only: the copy holds a read snapshot of hot, never its write lock,
        # so exporters keep writing while the archive is updated.
        conn.execute("ATTACH DATABASE ? AS hot", (hot.resolve().as_uri() + "?mode=ro",))
        conn.execute("BEGIN IMMEDIATE")
        try:
            check_config(load_config())  # the live config, as the old guard re-read it
            stats.bound = _bind_full(conn, plan)
            instance, revision = conn.execute(
                "SELECT a.instance, r.revision FROM hot.context_access_state a, "
                "hot.context_replica_content_state r WHERE a.id=1 AND r.id=1"
            ).fetchone()
            if instance != plan.instance:
                raise TieringRefused(
                    "instance_mismatch",
                    "the hot database's instance changed during sync",
                )
            changed = _controls_differ(conn)
            if changed:
                raise TieringRefused(
                    "controls_changed",
                    f"{changed} differs between hot and full after reconciliation",
                    table=changed,
                )
            # Re-apply durable intent to full against this snapshot before any copy.
            reconcile_local_retirements(conn)
            clean = _copy_payload(conn, stats)
            conn.execute(
                f"UPDATE main.{MIRROR_TABLE} SET last_source_revision=? WHERE id=1",
                (revision if clean else None,),
            )
            stats.sessions_total_full = conn.execute(
                "SELECT COUNT(*) FROM main.sessions"
            ).fetchone()[0]
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            reason = (
                "orphan_row" if "FOREIGN KEY" in str(exc) else "constraint_violation"
            )
            raise TieringRefused(reason, str(exc)) from exc
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return stats


def _copy_payload(conn: sqlite3.Connection, stats: SyncStats) -> bool:
    """Copy every payload table in registry order; True when hot ⊆ full afterwards."""
    from .tiering_registry import PAYLOAD, Role, columns

    cols = {entry.name: columns(conn, entry.name, "main") for entry in PAYLOAD}
    message_cols = ", ".join(_q(c) for c in cols["messages"])
    reference_cols = ", ".join(_q(c) for c in cols["file_references"])

    # Sessions whose children must be replaced, decided BEFORE the session
    # upsert. ``content_hash`` alone is not enough: the exporters never write it
    # (exporters/base.py session upsert), so a re-export with new turns keeps
    # NULL == NULL. A child row added, changed or removed marks the session too.
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS tier_changed (id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM temp.tier_changed")
    conn.execute(
        "INSERT OR IGNORE INTO temp.tier_changed SELECT h.id FROM hot.sessions h "
        "LEFT JOIN main.sessions f ON f.id = h.id "
        "WHERE f.id IS NULL OR f.content_hash IS NOT h.content_hash"
    )
    for table in ("messages", "file_references"):
        key = ("id",)
        conn.execute(
            "INSERT OR IGNORE INTO temp.tier_changed SELECT DISTINCT session_id FROM ("
            + _missing_sql(
                table, cols[table], key, keys_only=False, select=["session_id"]
            )
            + ")"
        )
        conn.execute(
            f"INSERT OR IGNORE INTO temp.tier_changed SELECT DISTINCT x.session_id "
            f"FROM main.{table} x WHERE x.session_id IN (SELECT id FROM hot.sessions) "
            f"AND NOT EXISTS (SELECT 1 FROM hot.{table} h WHERE h.id = x.id)"
        )
    session_rows = conn.execute(
        _missing_sql(
            "sessions", cols["sessions"], ("id",), keys_only=False, select=["id"]
        )
    ).fetchall()
    touched = {row[0] for row in session_rows} | {
        row[0] for row in conn.execute("SELECT id FROM temp.tier_changed")
    }
    stats.sessions_synced = len(touched)

    def record(table: str, written: int) -> None:
        if written:
            stats.rows_copied[table] = stats.rows_copied.get(table, 0) + written

    for entry in PAYLOAD:
        table, key = entry.name, entry.key
        if table == "messages":
            # message_concepts references messages with NO ACTION: clear it for
            # the replaced messages first (the mutable phase restores hot's rows).
            # The DELETE then cascades file_references, scrub_log, native message
            # sources and embeddings; each is restored below from hot.
            conn.execute(
                "DELETE FROM main.message_concepts WHERE message_id IN (SELECT id FROM "
                "main.messages WHERE session_id IN (SELECT id FROM temp.tier_changed))"
            )
            conn.execute(
                "DELETE FROM main.messages WHERE session_id IN (SELECT id FROM temp.tier_changed)"
            )
            written = conn.execute(
                f"INSERT INTO main.messages ({message_cols}) SELECT {message_cols} "
                "FROM hot.messages WHERE session_id IN (SELECT id FROM temp.tier_changed)"
            ).rowcount
            stats.messages_synced = written
            record(table, written)
        elif table == "file_references":
            conn.execute(
                "DELETE FROM main.file_references WHERE session_id IN "
                "(SELECT id FROM temp.tier_changed)"
            )
            written = conn.execute(
                f"INSERT INTO main.file_references ({reference_cols}) SELECT {reference_cols} "
                "FROM hot.file_references WHERE session_id IN (SELECT id FROM temp.tier_changed)"
            ).rowcount
            stats.file_references_synced = written
            record(table, written)
        elif entry.role is Role.PAYLOAD_IMMUTABLE:
            _refuse_immutable_collision(conn, table, cols[table], key)
            missing = _missing_sql(table, cols[table], key, keys_only=True)
            col_list = ", ".join(_q(c) for c in cols[table])
            record(
                table,
                conn.execute(
                    f"INSERT INTO main.{_q(table)} ({col_list}) {missing}"
                ).rowcount,
            )
        else:
            record(table, conn.execute(_upsert_sql(table, cols[table], key)).rowcount)
    conn.execute("DROP TABLE temp.tier_changed")

    # A row-maintenance trigger in full (``trg_*_updated_at_*``, ``*_sync_key``)
    # can rewrite a just-copied mutable row. One more upsert pass converges it;
    # if anything still differs, the receipt is withheld so the next run is not
    # a fast path and prune's proof stays false until it matches.
    clean = True
    for entry in PAYLOAD:
        if entry.role is Role.PAYLOAD_IMMUTABLE or entry.role is Role.CHILDREN_REPLACE:
            continue
        probe = _missing_sql(entry.name, cols[entry.name], entry.key, keys_only=False)
        if conn.execute(probe + " LIMIT 1").fetchone():
            conn.execute(_upsert_sql(entry.name, cols[entry.name], entry.key))
            if conn.execute(probe + " LIMIT 1").fetchone():
                logger.warning(
                    "sync_to_full: %s still differs after the upsert", entry.name
                )
                clean = False
    return clean


def _refuse_immutable_collision(
    conn: sqlite3.Connection, table: str, cols: list[str], key: tuple[str, ...]
) -> None:
    """An overlapping immutable key must be column-equal (council pass 7, C1)."""
    on = " AND ".join(f"x.{_q(c)} = h.{_q(c)}" for c in key)
    same = " AND ".join(f"x.{_q(c)} IS h.{_q(c)}" for c in cols)
    row = conn.execute(
        f"SELECT {', '.join(f'h.{_q(c)}' for c in key)} FROM hot.{_q(table)} h "
        f"JOIN main.{_q(table)} x ON {on} WHERE NOT ({same}) LIMIT 1"
    ).fetchone()
    if row is not None:
        raise TieringRefused(
            "immutable_collision",
            f"{table} key {tuple(row)!r} differs between hot and full",
            table=table,
            key=tuple(row),
        )


def _require_legacy_copy(hot, full, config):
    """The old body-only copier must not discard modern lineage or lifecycle state."""
    from contextlib import closing
    from .replication.legacy import check_config, check_database

    check_config(config)
    for path in (hot, full):
        if path.exists():
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as conn:
                check_database(conn)


def _check_legacy_attached(conn, schema, config):
    from .replication.legacy import check_config, check_database

    check_config(config)
    check_config(load_config())
    check_database(conn)
    check_database(conn, schema)


# ---------------------------------------------------------------------------
# Snapshots of the full DB (with retention)
# ---------------------------------------------------------------------------


def create_snapshot(
    full: Path | None = None,
    backup_dir: Path | None = None,
    retain: int | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    """Point-in-time copy of the full DB into the snapshot dir, rotating old ones.

    Uses ``VACUUM INTO`` — the snapshot is transactionally consistent AND
    compacted (free pages dropped, no WAL sidecars). Falls back to the
    online backup API on SQLite builds without VACUUM INTO support.
    """
    cfg = config or load_config()
    full = full or get_full_db_path(cfg)
    if full is None or not full.exists():
        raise FileNotFoundError(f"Full database not found: {full}")
    if backup_dir is None:
        backup_dir = Path(
            cfg["database"].get("snapshot_dir") or cfg["database"]["backup_dir"]
        )
    if retain is None:
        retain = int(cfg["database"].get("snapshot_retention", 7))

    ensure_leaf_dir(backup_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = backup_dir / f"{full.stem}_snapshot_{timestamp}.db"
    # Same-second collision guard (e.g. auto-snapshot right after manual one)
    n = 1
    while snapshot.exists():
        snapshot = backup_dir / f"{full.stem}_snapshot_{timestamp}_{n}.db"
        n += 1

    src = sqlite3.connect(f"file:{full}?mode=ro", uri=True)
    try:
        # The snapshot is a whole copy of the 0600 record (F-AST-14). Left to
        # VACUUM INTO, SQLite creates it under the umask (0644 under 022), so
        # it is created here, owner-only and empty (VACUUM INTO accepts an
        # empty file), and SQLite writes every byte into that. O_EXCL: the
        # loop above chose an unused name; never write into someone else's.
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        try:
            try:
                src.execute("VACUUM INTO ?", (str(snapshot),))
            except sqlite3.OperationalError:  # pragma: no cover - old SQLite
                dst = sqlite3.connect(snapshot)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
        except BaseException:
            # An empty or partial file would read as the newest snapshot to
            # maybe_snapshot and hold back the next one for a whole interval.
            snapshot.unlink(missing_ok=True)
            raise
    finally:
        src.close()

    # Rotate: keep the newest `retain` snapshots for this stem.
    pattern = f"{full.stem}_snapshot_*.db"
    snapshots = sorted(backup_dir.glob(pattern))
    for old in snapshots[:-retain] if retain > 0 else []:
        old.unlink()
        logger.info("snapshot rotation: removed %s", old.name)

    logger.info("snapshot created: %s", snapshot)
    return snapshot


def maybe_snapshot(config: dict[str, Any] | None = None) -> Path | None:
    """Create a snapshot if the newest one is older than the configured interval.

    Called after a successful sync so the record gets periodic point-in-time
    protection without a scheduler. ``database.snapshot_interval_days`` of 0
    disables auto-snapshots (manual ``session-maint snapshot`` still works).
    """
    cfg = config or load_config()
    interval_days = int(cfg["database"].get("snapshot_interval_days", 7))
    if interval_days <= 0:
        return None
    full = get_full_db_path(cfg)
    if full is None or not full.exists():
        return None
    backup_dir = Path(
        cfg["database"].get("snapshot_dir") or cfg["database"]["backup_dir"]
    )
    if backup_dir.exists():
        snapshots = sorted(backup_dir.glob(f"{full.stem}_snapshot_*.db"))
        if snapshots:
            age_days = (
                datetime.now().timestamp() - snapshots[-1].stat().st_mtime
            ) / 86400
            if age_days < interval_days:
                return None
    return create_snapshot(config=cfg)


# ---------------------------------------------------------------------------
# Prune (hot DB, verify-then-delete)
# ---------------------------------------------------------------------------


def prune_hot(
    days: int = 30,
    hot: Path | None = None,
    full: Path | None = None,
    dry_run: bool = True,
    vacuum: bool = True,
    keep_session_ids: set[str] | None = None,
    config: dict[str, Any] | None = None,
) -> PruneStats:
    """Delete sessions older than ``days`` from the hot DB — but only those
    verified present in the full DB.

    Modern schemas also require exact message-row retention and a complete
    context/learner snapshot in full. This conservative whole-context check can
    retain more hot sessions when any report is not yet archived. Eviction removes
    dependent owned records from hot without permanently retiring their identities;
    the verified copies remain in full. It is distinct from global forgetting.
    Sessions failing verification or in ``keep_session_ids`` are retained.
    """
    cfg = config or load_config()
    hot = hot or get_db_path(cfg)
    full = full or get_full_db_path(cfg)
    if full is None:
        raise ValueError(
            "database.full_db_path is not configured — prune refuses to run "
            "without a full DB to verify against"
        )
    if not full.exists():
        raise FileNotFoundError(
            f"Full database not found: {full} — is the volume mounted? "
            "Run 'session-maint sync-full' first."
        )
    if not hot.exists():
        raise FileNotFoundError(f"Hot database not found: {hot}")

    # R-20: this cutoff is compared against sessions.updated_at (UTC-sourced
    # transcript timestamps) and feeds prune's DELETE. A naive local-time
    # cutoff shifts the boundary by the machine's UTC offset.
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    size_before = hot.stat().st_size
    stats = PruneStats(dry_run=dry_run)

    conn = sqlite3.connect(hot)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        modern = conn.execute("PRAGMA user_version").fetchone()[0] >= 41
        conn.execute("PRAGMA foreign_keys=ON" if modern else "PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS full", (str(full),))
        if modern:
            # Hold verification and eviction in the same attached-DB transaction.
            conn.execute("BEGIN IMMEDIATE")

        # A session's age is its newest known timestamp -- the rule delete and
        # archive apply (F-AST-06, maintenance._SESSION_AGE_SQL). updated_at
        # is NULL for every Kiro v1 conversation and for any harness that gave
        # none; the old predicate (updated_at < ? OR updated_at IS NULL) made
        # such a session "older than N days" however new it was, so a
        # conversation from yesterday was evicted from hot. Unknown age is
        # never old: those sessions are kept and counted.
        age = (
            "COALESCE(s.updated_at, s.created_at, "
            "(SELECT MAX(m.timestamp) FROM main.messages m WHERE m.session_id = s.id))"
        )
        stats.skipped_undated = conn.execute(
            f"SELECT COUNT(*) FROM main.sessions s WHERE {age} IS NULL"
        ).fetchone()[0]
        candidate_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT s.id FROM main.sessions s WHERE {age} < ?",
                (cutoff,),
            )
        ]
        if keep_session_ids:
            candidate_ids = [c for c in candidate_ids if c not in keep_session_ids]
        # Invariant 3: a session that owns learner records is never a candidate.
        # Excluded here, ahead of verification, so it is reported as anchored
        # rather than "not in full DB" on both the modern and legacy paths.
        anchored = _anchored_session_ids(conn) & set(candidate_ids)
        if anchored:
            candidate_ids = [c for c in candidate_ids if c not in anchored]
            stats.skipped_anchored = len(anchored)
            stats.anchored_ids = sorted(anchored)
        stats.candidates = len(candidate_ids)
        if not candidate_ids:
            return stats

        conn.execute("CREATE TEMP TABLE cand_ids (id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO cand_ids VALUES (?)", [(c,) for c in candidate_ids]
        )

        # Verified = id present in full, content_hash matches, and full has
        # at least as many messages for the session as hot does.
        verified_rows = conn.execute(
            """
            SELECT h.id FROM main.sessions h
            JOIN cand_ids c ON c.id = h.id
            JOIN full.sessions f ON f.id = h.id
               AND COALESCE(f.content_hash, '') = COALESCE(h.content_hash, '')
            WHERE (SELECT COUNT(*) FROM full.messages fm WHERE fm.session_id = h.id)
                  >= (SELECT COUNT(*) FROM main.messages hm WHERE hm.session_id = h.id)
            """
        ).fetchall()
        verified = {r["id"] for r in verified_rows}
        if modern:
            if not _archive_context_complete(conn):
                verified = set()
            else:
                columns = [
                    r[1] for r in conn.execute("PRAGMA main.table_info(messages)")
                ]
                selected = ",".join(
                    '"' + column.replace('"', '""') + '"' for column in columns
                )
                verified = {
                    sid
                    for sid in verified
                    if not conn.execute(
                        "SELECT 1 FROM (SELECT * FROM main.sessions WHERE id=? "
                        "EXCEPT SELECT * FROM full.sessions WHERE id=?) LIMIT 1",
                        (sid, sid),
                    ).fetchone()
                    and not conn.execute(
                        f"SELECT 1 FROM (SELECT {selected} FROM main.messages WHERE session_id=? "
                        f"EXCEPT SELECT {selected} FROM full.messages WHERE session_id=?) LIMIT 1",
                        (sid, sid),
                    ).fetchone()
                    and not conn.execute(
                        "SELECT 1 FROM full.context_tombstones WHERE session_id=?",
                        (sid,),
                    ).fetchone()
                }
        stats.verified = len(verified)
        stats.skipped_unverified = stats.candidates - stats.verified
        stats.skipped_ids = [c for c in candidate_ids if c not in verified]

        if dry_run or not verified:
            stats.messages_deleted = (
                conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id IN "
                    f"({','.join('?' * len(verified))})",
                    list(verified),
                ).fetchone()[0]
                if verified
                else 0
            )
            return stats

        session_child = _dependent_tables(conn, "sessions")
        message_child = _dependent_tables(conn, "messages")

        with conn:
            if modern:
                from .context.lifecycle import eviction, purge_session

                with eviction(conn):
                    for sid in verified:
                        stats.messages_deleted += conn.execute(
                            "SELECT count(*) FROM messages WHERE session_id=?", (sid,)
                        ).fetchone()[0]
                        purge_session(conn, sid, permanent=False)
                        stats.sessions_deleted += 1
            else:
                _prune_legacy_rows(conn, verified, session_child, message_child, stats)

        conn.execute("DETACH DATABASE full")
        if vacuum:
            conn.execute("VACUUM")
    finally:
        conn.close()

    stats.reclaimed_mb = (size_before - hot.stat().st_size) / 1024 / 1024
    logger.info(
        "prune: deleted %s sessions (%s messages), reclaimed %.1f MB, "
        "skipped %s unverified",
        stats.sessions_deleted,
        stats.messages_deleted,
        stats.reclaimed_mb,
        stats.skipped_unverified,
    )
    return stats


def _archive_context_complete(conn):
    """Whole-context retention proof by the table-role registry (hot=main, full).

    The same registry the mirror copies by (``tiering_registry``), so what is
    required in full is exactly what ``sync_to_full`` puts there (council pass
    7, C2): every payload row of hot is row-equal in full (``sessions`` and
    ``messages`` are proven per session by ``prune_hot``), the permanent
    controls are equal, full's foreign keys hold, and an unclassified table
    fails closed. Instance-local, peer-ledger and derived tables are neither
    copied nor required -- before, every ``context_*`` table counted, so the
    ``context_retention_origins`` row each export writes kept this false
    forever once anything was mirrored. Primary-key anti-joins, not EXCEPT.
    """
    from .tiering_registry import PAYLOAD, UnclassifiedTable, classify_database, columns

    try:
        classify_database(conn, "main")
    except UnclassifiedTable as exc:
        logger.warning("prune: %s -- nothing is evicted until this build knows it", exc)
        return False
    remote = set(_user_tables(conn, "full"))
    if conn.execute("PRAGMA full.foreign_key_check").fetchone():
        return False
    if _controls_differ(conn, "main", "full"):
        return False
    for entry in PAYLOAD:
        if entry.name in ("sessions", "messages"):
            continue  # proven per session, with the content hash, in prune_hot
        if entry.name not in remote:
            return False
        cols = columns(conn, entry.name, "main")
        if cols != columns(conn, entry.name, "full"):
            return False
        probe = _missing_sql(
            entry.name, cols, entry.key, keys_only=False, source="main", archive="full"
        )
        if conn.execute(probe + " LIMIT 1").fetchone():
            return False
    return True


def _prune_legacy_rows(conn, verified, session_child, message_child, stats):
    conn.execute("CREATE TEMP TABLE prune_ids (id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO prune_ids VALUES (?)", [(v,) for v in verified])
    # message-scoped dependents first (need message ids present)
    for table, fk_col in message_child:
        conn.execute(
            f"DELETE FROM {table} WHERE {fk_col} IN "
            "(SELECT id FROM messages WHERE session_id IN "
            "(SELECT id FROM prune_ids))"
        )
    stats.messages_deleted = conn.execute(
        "DELETE FROM messages WHERE session_id IN (SELECT id FROM prune_ids)"
    ).rowcount
    for table, fk_col in session_child:
        conn.execute(
            f"DELETE FROM {table} WHERE {fk_col} IN (SELECT id FROM prune_ids)"
        )
    if _table_exists(conn, "file_references"):
        conn.execute(
            "DELETE FROM file_references WHERE session_id IN (SELECT id FROM prune_ids)"
        )
    stats.sessions_deleted = conn.execute(
        "DELETE FROM sessions WHERE id IN (SELECT id FROM prune_ids)"
    ).rowcount
    conn.execute("DROP TABLE prune_ids")


# ---------------------------------------------------------------------------
# Refocus (focus-change data movement: pull relevant, prune stale)
# ---------------------------------------------------------------------------


def topics_fts_query(topics: list[str]) -> str:
    """Build an FTS5 query matching any of the focus topics.

    Each topic becomes a quoted phrase (safe against FTS operators in topic
    names); topics are OR-ed. "sql window functions" matches messages
    containing that phrase; single-word topics match stemmed occurrences.
    """
    phrases = []
    for topic in topics:
        cleaned = str(topic).replace('"', " ").strip()
        if cleaned:
            phrases.append(f'"{cleaned}"')
    return " OR ".join(phrases)


def _focus_session_ids(
    conn: sqlite3.Connection, schema: str, fts_query: str, since: str | None = None
) -> set[str]:
    """Session ids in ``schema`` whose message content matches the focus query.

    Also includes study sessions whose recorded topic matches (when the
    study_sessions table exists in that schema).
    """
    if not fts_query:
        return set()
    params: list = [fts_query]
    sql = (
        "SELECT DISTINCT m.session_id FROM ("
        f"SELECT rowid AS fts_rowid FROM {schema}.messages_fts "
        "WHERE messages_fts MATCH ?"
        ") fx "
        f"JOIN {schema}.messages m ON m.rowid = fx.fts_rowid"
    )
    if since:
        sql += " WHERE m.timestamp >= ?"
        params.append(since)
    ids = {r[0] for r in conn.execute(sql, params).fetchall() if r[0]}

    if _table_exists(conn, "study_sessions", schema):
        # study_sessions.topic is free text — match loosely per topic term.
        rows = conn.execute(
            f"SELECT session_id, topic FROM {schema}.study_sessions "
            "WHERE session_id IS NOT NULL AND topic IS NOT NULL"
        ).fetchall()
        terms = [t.strip('"').lower() for t in fts_query.split(" OR ")]
        for sid, topic in rows:
            low = str(topic).lower()
            if any(term and (term in low or low in term) for term in terms):
                ids.add(sid)
    return ids


def refocus(
    topics: list[str],
    days: int = 30,
    hot: Path | None = None,
    full: Path | None = None,
    dry_run: bool = False,
    config: dict[str, Any] | None = None,
) -> RefocusStats:
    """Apply a focus change to the hot DB: pull then prune.

    1. PULL — sessions from the last ``days`` days in the full DB whose
       content matches any focus topic, and which are missing from the hot
       DB, are copied in (messages fire the hot FTS triggers).
    2. PRUNE — hot sessions older than ``days`` matching NO focus topic are
       pruned under the standard verify-in-full invariant. Recent sessions
       survive regardless of topic (cheap, and resume/struggles need them).

    Pull always runs before prune: an interruption leaves the hot DB with
    extra data, never with less.
    """
    cfg = config or load_config()
    hot = hot or get_db_path(cfg)
    full = full or get_full_db_path(cfg)
    if full is None:
        raise ValueError(
            "database.full_db_path is not configured — refocus needs the "
            "full DB to pull history from and verify pruning against"
        )
    if not full.exists():
        raise FileNotFoundError(
            f"Full database not found: {full} — is the volume mounted? "
            "Focus is saved; run 'studyloop focus apply' when it is available."
        )
    if not hot.exists():
        raise FileNotFoundError(f"Hot database not found: {hot}")

    _require_legacy_copy(hot, full, cfg)

    fts_query = topics_fts_query(topics)
    if not fts_query:
        raise ValueError("refocus requires at least one topic")
    # R-20: gates messages.timestamp (UTC-sourced) -- same naive-local-time
    # skew as prune's cutoff above.
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    stats = RefocusStats(topics=list(topics), dry_run=dry_run)

    conn = sqlite3.connect(hot)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS full", (str(full),))
        conn.execute("BEGIN IMMEDIATE")
        _check_legacy_attached(conn, "full", cfg)

        # ---- 1. PULL: focus-matching recent sessions missing from hot ----
        full_focus_ids = _focus_session_ids(conn, "full", fts_query, since=since)
        hot_ids = {r["id"] for r in conn.execute("SELECT id FROM main.sessions")}
        to_pull = sorted(full_focus_ids - hot_ids)
        stats.pulled_sessions = len(to_pull)

        if to_pull and not dry_run:
            with conn:
                conn.execute("CREATE TEMP TABLE pull_ids (id TEXT PRIMARY KEY)")
                conn.executemany(
                    "INSERT INTO pull_ids VALUES (?)", [(p,) for p in to_pull]
                )
                _copy_table(
                    conn,
                    "sessions",
                    "full",
                    where="WHERE id IN (SELECT id FROM pull_ids)",
                    replace=True,
                )
                stats.pulled_messages = _copy_table(
                    conn,
                    "messages",
                    "full",
                    where="WHERE session_id IN (SELECT id FROM pull_ids)",
                )
                if _table_exists(conn, "file_references") and _table_exists(
                    conn, "file_references", "full"
                ):
                    _copy_table(
                        conn,
                        "file_references",
                        "full",
                        where="WHERE session_id IN (SELECT id FROM pull_ids)",
                    )
                conn.execute("DROP TABLE pull_ids")
                _check_legacy_attached(conn, "full", cfg)

        # ---- 2. Identify hot sessions matching focus (never pruned) ----
        keep_ids = _focus_session_ids(conn, "main", fts_query)
        stats.kept_in_focus = len(keep_ids)
        _check_legacy_attached(conn, "full", cfg)
        if conn.in_transaction:
            conn.rollback()
        conn.execute("DETACH DATABASE full")
    finally:
        conn.close()

    # ---- 3. PRUNE: old, non-focus sessions (standard invariant) ----
    stats.prune = prune_hot(
        days=days,
        hot=hot,
        full=full,
        dry_run=dry_run,
        keep_session_ids=keep_ids,
        config=cfg,
    )
    logger.info(
        "refocus(%s): pulled %s session(s), kept %s in focus, pruned %s",
        ", ".join(topics),
        stats.pulled_sessions,
        stats.kept_in_focus,
        stats.prune.sessions_deleted,
    )
    return stats


# ---------------------------------------------------------------------------
# Daily trigger (first coding session of the day)
# ---------------------------------------------------------------------------


def _marker_path() -> Path:
    return get_config_dir() / _MARKER_FILE


def _lock_path() -> Path:
    return get_config_dir() / _LOCK_FILE


def write_sync_marker() -> None:
    """Record that today's sync completed (called by the sync process)."""
    _marker_path().write_text(date.today().isoformat())


def acquire_sync_lock() -> bool:
    """Atomically acquire the sync lockfile. Returns False if already held."""
    lock = _lock_path()
    if lock.exists():
        age = datetime.now().timestamp() - lock.stat().st_mtime
        if age < _LOCK_STALE_SECONDS:
            return False
        logger.warning("removing stale sync lock (age %.0fs)", age)
        lock.unlink(missing_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as fh:
        fh.write(str(os.getpid()))
    return True


def release_sync_lock() -> None:
    _lock_path().unlink(missing_ok=True)


def maybe_spawn_sync(config: dict[str, Any] | None = None) -> bool:
    """If tiering is enabled, spawn a background hot -> full sync.

    Called from session-touching code paths (session export, study session
    start). Cadence is governed by ``database.sync_mode``:

    - ``always`` (default): spawn on every trigger — the record trails the
      spool by seconds. The lockfile serialises concurrent attempts and the
      content-hash diff makes each run sub-second.
    - ``daily``: spawn only on the first trigger of the day (marker file).

    All checks are cheap; the spawned process does the real work and owns
    the lock. Never raises — a failed sync must not break a session.

    Returns True when a background sync was spawned.
    """
    try:
        cfg = config or load_config()
        full = get_full_db_path(cfg)
        if full is None:
            return False
        mode = str(cfg.get("database", {}).get("sync_mode", "always")).lower()
        if mode == "daily":
            marker = _marker_path()
            if (
                marker.exists()
                and marker.read_text().strip() == date.today().isoformat()
            ):
                return False
        # Mount-safety: the full DB's grandparent must exist (we only ever
        # create the leaf directory). If the volume is unmounted, skip
        # quietly — the content-hash diff is stateless, so the first sync
        # after remount catches up everything accumulated while offline.
        if not full.parent.parent.exists():
            logger.info(
                "sync skipped: %s unavailable (volume not mounted?)",
                full.parent,
            )
            return False
        if _lock_path().exists():
            # A sync is (probably) already running; it will pick up this
            # trigger's data anyway, or the next trigger will.
            return False
        subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "agent_session_tools.maintenance",
                "sync-full",
                "--quiet",
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("background incremental sync spawned")
        return True
    except Exception:  # pragma: no cover - defensive: never break a session
        logger.exception("maybe_spawn_sync failed")
        return False


# Backwards-compatible alias (pre-sync_mode name).
maybe_spawn_daily_sync = maybe_spawn_sync
