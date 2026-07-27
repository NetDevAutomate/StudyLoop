"""Database tiering: hot (local) / full (external) session store management.

The tiering model:

- **Hot DB** (``~/.config/studyloop/sessions.db``) — the live database every
  code-harness exporter writes to. Always local so session exports never
  depend on an external volume being mounted. May be pruned to the last
  N days on machines with small drives.
- **Full DB** (``database.full_db_path`` in config.yaml, e.g. on an external
  volume) — the complete, append-mostly history. Maintained by
  :func:`sync_to_full`, an idempotent content-hash based upsert.
- **Snapshots** (``database.backup_dir``) — periodic point-in-time copies of
  the full DB with retention, protecting against corruption that an
  incremental sync would faithfully propagate.

Safety invariants:

- :func:`prune_hot` never deletes a session that is not verified present in
  the full DB (id + content_hash match + message-count check). Worst case it
  frees less space; it is mechanically incapable of losing data.
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
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
_SESSION_CHILD_TABLES = ("session_embeddings", "session_learning_metadata")
_MESSAGE_CHILD_TABLES = ("message_embeddings", "message_concepts")

# Tables synced into the full DB (with their FK parents). Embeddings are
# derived data and deliberately NOT synced — they can be regenerated in the
# full DB if semantic search over history is ever needed.
_SYNCED_TABLES = ("sessions", "messages", "file_references")

_FTS_INTERNAL_PREFIX = "messages_fts"

_MARKER_FILE = ".last_full_sync"
_LOCK_FILE = ".full_sync.lock"
_LOCK_STALE_SECONDS = 3600


# ---------------------------------------------------------------------------
# Stats dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FtsIntegrity:
    """Result of the FTS index invariant check."""

    messages_with_content: int
    fts_rows: int

    @property
    def drift(self) -> int:
        return self.fts_rows - self.messages_with_content

    @property
    def healthy(self) -> bool:
        return self.drift == 0


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


@dataclass
class PruneStats:
    """Result of pruning the hot DB."""

    candidates: int = 0
    verified: int = 0
    skipped_unverified: int = 0
    sessions_deleted: int = 0
    messages_deleted: int = 0
    reclaimed_mb: float = 0.0
    dry_run: bool = False
    skipped_ids: list[str] = field(default_factory=list)


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
    """Create *only* the final directory component of ``path``.

    Refuses when the parent is missing. This is the mount-safety guard: on
    macOS an unmounted external volume means ``/Volumes/<name>`` does not
    exist, and a recursive mkdir would silently create a real directory on
    the boot volume that later shadows the mount.
    """
    if path.exists():
        return
    if not path.parent.exists():
        raise FileNotFoundError(
            f"Parent directory missing: {path.parent} — is the volume mounted? "
            "Create the directory structure once manually, then retry."
        )
    path.mkdir()


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, table: str, schema: str = "main") -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(
    conn: sqlite3.Connection, table: str, schema: str = "main"
) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _user_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [
        r[0]
        for r in rows
        if not r[0].startswith(_FTS_INTERNAL_PREFIX) or r[0] == "messages_fts"
        # keep messages_fts out too — it is rebuilt via triggers, never copied
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
) -> int:
    """Copy ``table`` rows using the column intersection of both schemas."""
    src_cols = _table_columns(conn, table, src_schema)
    dest_cols = _table_columns(conn, table, dest_schema)
    cols = [c for c in src_cols if c in dest_cols]
    if not cols:
        return 0
    col_list = ", ".join(cols)
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    cur = conn.execute(
        f"{verb} INTO {dest_schema}.{table} ({col_list}) "
        f"SELECT {col_list} FROM {src_schema}.{table} {where}"
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# FTS integrity (the 45GB-bug guardrail)
# ---------------------------------------------------------------------------


def fts_integrity(conn: sqlite3.Connection) -> FtsIntegrity:
    """Check the FTS invariant: one index row per message with content.

    A drifted index means the sync triggers were bypassed (bulk re-insert
    bug) or messages were deleted outside the triggers. Historical versions
    of the exporter re-indexed every message on every run, growing one DB
    to 45GB (586 duplicate index copies of 32MB of content).
    """
    messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE content IS NOT NULL"
    ).fetchone()[0]
    fts_rows = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    return FtsIntegrity(messages_with_content=messages, fts_rows=fts_rows)


def repair_fts(conn: sqlite3.Connection) -> FtsIntegrity:
    """Rebuild the FTS index from the messages table (idempotent).

    Note: FTS5's built-in ``('rebuild')`` command rebuilds the inverted index
    from the FTS table's *own* content store, so it preserves duplicate rows.
    A drifted standalone FTS table must be cleared and repopulated from the
    source of truth instead.
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
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('optimize')")
    return fts_integrity(conn)


# ---------------------------------------------------------------------------
# Compact (rescue a bloated DB into a clean one)
# ---------------------------------------------------------------------------


def compact_database(source: Path, dest: Path) -> CompactStats:
    """Copy all real data from ``source`` into a fresh, migrated DB at ``dest``.

    The FTS index is rebuilt exactly once via the insert triggers on the
    destination — duplicated index rows in the source are left behind.
    ``source`` is opened read-only (immutable) and never modified.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")
    if dest.exists():
        raise FileExistsError(
            f"Destination already exists, refusing to overwrite: {dest}"
        )

    from agent_session_tools.export_sessions import init_db

    ensure_leaf_dir(dest.parent)
    # init_db creates schema + migrations; reopen with URI processing enabled
    # so the immutable ATTACH below is honoured (a non-URI connection would
    # treat 'file:...?immutable=1' as a literal filename).
    init_db(str(dest)).close()
    conn = sqlite3.connect(f"file:{dest}", uri=True)
    stats = CompactStats(source_size_mb=source.stat().st_size / 1024 / 1024)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"ATTACH DATABASE 'file:{source}?immutable=1' AS src")

        src_tables = set(_user_tables(conn, "src")) - {"messages_fts"}
        dest_tables = set(_user_tables(conn, "main")) - {"messages_fts"}
        common = src_tables & dest_tables
        # Dependency order: parents before children; messages last of the
        # core pair so session FKs resolve. Everything else after.
        ordered = [t for t in ("sessions", "messages") if t in common]
        ordered += sorted(common - {"sessions", "messages"})

        with conn:
            for table in ordered:
                copied = _copy_table(conn, table, "src")
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
# Incremental sync (hot -> full)
# ---------------------------------------------------------------------------


def sync_to_full(
    hot: Path | None = None,
    full: Path | None = None,
    config: dict[str, Any] | None = None,
) -> SyncStats:
    """Idempotently upsert new/changed sessions from the hot DB into the full DB.

    Change detection is by ``content_hash`` (not timestamps), so machine
    clock differences and re-exports are handled: a session is copied when
    it is missing from the full DB or its content hash differs. Messages of
    a changed session are replaced wholesale; the full DB's FTS triggers
    keep its index consistent.
    """
    cfg = config or load_config()
    hot = hot or get_db_path(cfg)
    full = full or get_full_db_path(cfg)
    if full is None:
        raise ValueError(
            "database.full_db_path is not configured — set it in config.yaml "
            "to enable tiering"
        )
    if not hot.exists():
        raise FileNotFoundError(f"Hot database not found: {hot}")

    from agent_session_tools.export_sessions import init_db

    ensure_leaf_dir(full.parent)
    conn = init_db(str(full))
    stats = SyncStats()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"ATTACH DATABASE '{hot}' AS hot")

        with conn:
            conn.execute(
                """
                CREATE TEMP TABLE changed_ids AS
                SELECT h.id FROM hot.sessions h
                LEFT JOIN main.sessions f ON f.id = h.id
                WHERE f.id IS NULL
                   OR COALESCE(f.content_hash, '') != COALESCE(h.content_hash, '')
                """
            )
            stats.sessions_synced = conn.execute(
                "SELECT COUNT(*) FROM changed_ids"
            ).fetchone()[0]

            if stats.sessions_synced:
                # Replace messages of changed sessions (delete fires FTS
                # delete trigger; insert fires FTS insert trigger).
                conn.execute(
                    "DELETE FROM main.messages WHERE session_id IN "
                    "(SELECT id FROM changed_ids)"
                )
                stats.messages_synced = _copy_table(
                    conn,
                    "messages",
                    "hot",
                    where="WHERE session_id IN (SELECT id FROM changed_ids)",
                )
                _copy_table(
                    conn,
                    "sessions",
                    "hot",
                    where="WHERE id IN (SELECT id FROM changed_ids)",
                    replace=True,
                )
                if _table_exists(conn, "file_references") and _table_exists(
                    conn, "file_references", "hot"
                ):
                    conn.execute(
                        "DELETE FROM main.file_references WHERE session_id IN "
                        "(SELECT id FROM changed_ids)"
                    )
                    stats.file_references_synced = _copy_table(
                        conn,
                        "file_references",
                        "hot",
                        where="WHERE session_id IN (SELECT id FROM changed_ids)",
                    )
            conn.execute("DROP TABLE changed_ids")

        stats.sessions_total_full = conn.execute(
            "SELECT COUNT(*) FROM main.sessions"
        ).fetchone()[0]
        conn.execute("DETACH DATABASE hot")
    finally:
        conn.close()

    logger.info(
        "sync_to_full: %s session(s) upserted, full DB now holds %s sessions",
        stats.sessions_synced,
        stats.sessions_total_full,
    )
    return stats


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
        try:
            src.execute("VACUUM INTO ?", (str(snapshot),))
        except sqlite3.OperationalError:  # pragma: no cover - old SQLite
            dst = sqlite3.connect(snapshot)
            try:
                src.backup(dst)
            finally:
                dst.close()
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

    Verification per session: same id in full DB, matching ``content_hash``,
    and the full DB holds at least as many messages for it. Sessions failing
    verification are skipped and reported, never deleted. Sessions in
    ``keep_session_ids`` (e.g. focus-topic matches during a refocus) are
    excluded from candidacy entirely. Learning tables (study_progress,
    concepts, card_reviews, ...) are never touched.
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

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    size_before = hot.stat().st_size
    stats = PruneStats(dry_run=dry_run)

    conn = sqlite3.connect(hot)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"ATTACH DATABASE '{full}' AS full")

        candidate_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM main.sessions "
                "WHERE updated_at < ? OR updated_at IS NULL",
                (cutoff,),
            )
        ]
        if keep_session_ids:
            candidate_ids = [c for c in candidate_ids if c not in keep_session_ids]
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
            conn.execute("CREATE TEMP TABLE prune_ids (id TEXT PRIMARY KEY)")
            conn.executemany(
                "INSERT INTO prune_ids VALUES (?)", [(v,) for v in verified]
            )
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
                    "DELETE FROM file_references WHERE session_id IN "
                    "(SELECT id FROM prune_ids)"
                )
            stats.sessions_deleted = conn.execute(
                "DELETE FROM sessions WHERE id IN (SELECT id FROM prune_ids)"
            ).rowcount
            conn.execute("DROP TABLE prune_ids")

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

    fts_query = topics_fts_query(topics)
    if not fts_query:
        raise ValueError("refocus requires at least one topic")
    since = (datetime.now() - timedelta(days=days)).isoformat()
    stats = RefocusStats(topics=list(topics), dry_run=dry_run)

    conn = sqlite3.connect(hot)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"ATTACH DATABASE '{full}' AS full")

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

        # ---- 2. Identify hot sessions matching focus (never pruned) ----
        keep_ids = _focus_session_ids(conn, "main", fts_query)
        stats.kept_in_focus = len(keep_ids)
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
