#!/usr/bin/env python3
"""Database maintenance utilities for session database.

This tool provides commands for database optimization, archiving,
schema inspection, and maintenance operations.
"""

import logging
import os
import sqlite3
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.replication.legacy import LegacySyncRefused
from agent_session_tools.config_loader import (
    get_backup_dir,
    get_db_path,
    get_log_path,
    load_config,
)
from agent_session_tools.deduplication import (
    auto_merge_safe_duplicates,
    list_all_duplicates,
    merge_duplicates,
)
from agent_session_tools.migrations import migrate

# Module-level logger — does NOT configure the root logger (no basicConfig here).
# Logging is set up in the app callback below, which only runs when this module
# is used as a CLI tool.  Library callers (tests, MCP server, sync.py) are
# unaffected.
logger = logging.getLogger(__name__)

# Lazy config / path cache — populated on first use so that importing this
# module at the top of another file has no file-system side effects.
_config: dict | None = None


def _get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_db_path() -> Path:
    return get_db_path(_get_config())


# Create Typer app with completion support
app = typer.Typer(
    name="session-maint",
    help="Database maintenance utilities for session database.",
    add_completion=True,
    rich_markup_mode="rich",
)


@app.callback()
def _setup_logging() -> None:
    """Configure logging when running as a CLI tool (not when imported as a library)."""
    cfg = _get_config()
    log_path = get_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"]),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )


# Global database path option
db_option = typer.Option("-d", "--db", help="Database path (default: from config)")
no_backup_option = typer.Option("--no-backup", help="Skip backup creation")


def _create_owner_only(path: Path) -> None:
    """Create path as an owner-only (0600) file before SQLite opens it.

    The session database is 0600 (export_sessions.init_db) and every copy of
    it must be too (F-AST-14). Letting sqlite3.connect create the file uses
    the process umask (0644 under the usual 022), and a chmod afterwards
    leaves the copy readable while SQLite writes it. Creating the file here
    with mode 0600 means SQLite writes every byte into an owner-only file;
    fchmod also tightens a file that already existed at this path. The
    process umask is not changed.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def create_backup(db_path: Path) -> Path | None:
    """Create a timestamped backup of the database, with rotation.

    Refuses (returns None) when the DB exceeds ``database.backup_max_mb`` —
    accumulating multi-GB full copies is how a 45GB disk incident happens.
    At that size, snapshot the full DB instead (``session-maint snapshot``).
    Old backups beyond ``database.backup_retention`` are rotated out.
    """
    cfg = _get_config()
    db_cfg = cfg.get("database", {})
    max_mb = float(db_cfg.get("backup_max_mb", 1024))
    size_mb = db_path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        print(
            f"⚠️  Skipping full-copy backup: {db_path.name} is {size_mb:.0f} MB "
            f"(limit {max_mb:.0f} MB). Use 'session-maint snapshot' / "
            "'session-maint sync-full' for large databases."
        )
        logger.warning(
            "backup skipped: %s is %.0f MB (limit %.0f MB)", db_path, size_mb, max_mb
        )
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = get_backup_dir(cfg)
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{db_path.stem}_backup_{timestamp}.db"
    # R-19c (M3 council, arbitration A2/X1 extension): a plain file copy of a
    # WAL-mode database can miss committed data still sitting in the
    # `-wal` file -- `shutil.copy2` (like `cp -p`) only ever sees the main
    # `.db` file. sqlite3.Connection.backup() reads through SQLite's own
    # backup API, which is WAL-aware (verified directly: a row committed but
    # not yet checkpointed was present in a `.backup()` copy and absent from
    # a `cp -p` of the same database at the same instant).
    source_conn = sqlite3.connect(db_path)
    try:
        _create_owner_only(backup_path)
        dest_conn = sqlite3.connect(backup_path)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    # Rotation: keep only the newest N backups for this database stem.
    retention = int(db_cfg.get("backup_retention", 5))
    if retention > 0:
        backups = sorted(backup_dir.glob(f"{db_path.stem}_backup_*.db"))
        for old in backups[:-retention]:
            old.unlink()
            logger.info("backup rotation: removed %s", old.name)

    logger.info(f"Backup created: {backup_path}")
    print(f"✅ Backup created: {backup_path}")
    return backup_path


def _owner_only_candidates(cfg: dict) -> list[tuple[str, Path]]:
    """Every local copy of the record, or index derived from it, the config names.

    Maintenance backups (``<stem>_backup_*.db`` in ``database.backup_dir``,
    whatever the stem: ``vacuum``/``reindex``/``delete --db`` back up any
    database under its own stem), snapshots (``<full stem>_snapshot_*.db`` in
    ``database.snapshot_dir``, or ``backup_dir`` when unset) and the vector
    sidecars (``<stem>.vec.db`` beside the hot and the full database, with
    their WAL/SHM/journal companions). The globs are non-recursive and the
    names are the ones this package writes, so nothing outside those
    directories, and nothing else inside them, is listed.
    """
    from agent_session_tools.embedding_store import sidecar_path
    from agent_session_tools.tiering import get_full_db_path

    db_cfg = cfg["database"]
    hot = Path(db_cfg["path"])
    full = get_full_db_path(cfg)
    backup_dir = Path(db_cfg["backup_dir"])
    snapshot_dir = Path(db_cfg.get("snapshot_dir") or backup_dir)

    found: list[tuple[str, Path]] = []
    if backup_dir.is_dir():
        found += [("backup", p) for p in sorted(backup_dir.glob("*_backup_*.db"))]
    if full is not None and snapshot_dir.is_dir():
        found += [
            ("snapshot", p)
            for p in sorted(snapshot_dir.glob(f"{full.stem}_snapshot_*.db"))
        ]
    for db in (hot, full):
        if db is None:
            continue
        sidecar = sidecar_path(db)
        for suffix in ("", "-wal", "-shm", "-journal"):
            companion = sidecar.with_name(sidecar.name + suffix)
            if companion.is_symlink() or companion.exists():
                found.append(("sidecar", companion))
    return found


def _owner_only_directories(cfg: dict) -> list[Path]:
    """The directories this package creates to hold copies of the record.

    ``database.backup_dir`` always; ``database.snapshot_dir`` (or
    ``backup_dir`` when unset) only when a full tier is configured, since
    without one no snapshot is ever written there. Deduplicated, in order.
    """
    db_cfg = cfg["database"]
    directories = [Path(db_cfg["backup_dir"])]
    if db_cfg.get("full_db_path"):
        snapshot_dir = Path(db_cfg.get("snapshot_dir") or db_cfg["backup_dir"])
        if snapshot_dir not in directories:
            directories.append(snapshot_dir)
    return directories


def _fix_perms(cfg: dict, dry_run: bool = False, remote: bool = False) -> int:
    """Chmod pre-existing copies of the record to 0600 and report counts (D#2).

    Snapshots, backups and sidecars are created owner-only since 92186d77 /
    R-19c; copies made before that keep the mode the umask gave them (0644
    under 022). Only the files ``_owner_only_candidates`` lists are touched. A
    symlink is skipped and named: a chmod through it would change a file that
    may live outside the configured directories.

    The backup and snapshot directories themselves are tightened to 0700 when
    this user owns them (plan 5, larger #2 item 5): ``get_backup_dir`` and
    ``ensure_leaf_dir`` create them owner-only now, but a directory made
    before that -- or made by hand on a shared volume -- keeps the umask's
    0755, and this opt-in sweep is the only place that changes a directory
    it did not create. One owned by another user is named and left alone.

    ``remote`` runs the ``ssh … chmod 600`` this command otherwise only prints,
    once per configured endpoint path (plan 5, item C). Opt-in: an ssh that
    prompts would hang a local sweep, so ``BatchMode=yes`` and a connect
    timeout bound each call, and a failed endpoint is one reported row, never
    an abort -- the sweep finishes and the exit code says it was not clean.
    """
    import shlex

    from agent_session_tools.config_loader import get_endpoints

    verb = "Would tighten" if dry_run else "Tightened"
    print(f"\n{'=' * 50}")
    print(
        f"🔐 FIX PERMISSIONS (copies of the record -> 0600){' — DRY RUN' if dry_run else ''}"
    )
    print(f"{'=' * 50}")

    directories_tightened = 0
    failed: list[Path] = []
    for directory in _owner_only_directories(cfg):
        if directory.is_symlink():
            print(
                f"⚠️  Skipped directory {directory}: a symlink (its target is not swept)"
            )
            continue
        if not directory.is_dir():
            continue
        info = directory.stat()
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o077 == 0:
            continue
        if info.st_uid != os.geteuid():
            print(
                f"⚠️  Skipped directory {directory}: {mode:04o}, not owned by this user"
            )
            continue
        print(f"{'🔍' if dry_run else '🔧'} directory {directory}: {mode:04o} -> 0700")
        if not dry_run:
            try:
                os.chmod(directory, 0o700)
            except OSError as exc:
                failed.append(directory)
                print(
                    f"❌ directory {directory}: could not be changed "
                    f"({exc.strerror or exc})"
                )
                logger.warning(
                    "fix-perms: directory %s left at %04o: %s", directory, mode, exc
                )
                continue
            logger.info("fix-perms: directory %s %04o -> 0700", directory, mode)
        directories_tightened += 1

    tightened: list[Path] = []
    already = 0
    symlinks: list[Path] = []
    for kind, path in _owner_only_candidates(cfg):
        if path.is_symlink():
            symlinks.append(path)
            print(f"⚠️  Skipped {kind} {path}: a symlink (its target is not swept)")
            continue
        if not path.is_file():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode == 0o600:
            already += 1
            continue
        print(f"{'🔍' if dry_run else '🔧'} {kind} {path}: {mode:04o} -> 0600")
        if not dry_run:
            try:
                os.chmod(path, 0o600)
            except OSError as exc:
                # One unwritable copy (another user's file, a read-only volume)
                # must not abort the sweep: name it, keep going, exit non-zero.
                failed.append(path)
                print(f"❌ {kind} {path}: could not be changed ({exc.strerror or exc})")
                logger.warning(
                    "fix-perms: %s %s left at %04o: %s", kind, path, mode, exc
                )
                continue
            logger.info("fix-perms: %s %s %04o -> 0600", kind, path, mode)
        tightened.append(path)

    if not cfg["database"].get("full_db_path"):
        print(
            "ℹ️  database.full_db_path is not configured: no snapshots or full-tier "
            "sidecar to sweep."
        )
    summary = f"✅ {verb} {len(tightened)} file(s) to 0600; {already} already 0600"
    if directories_tightened:
        summary += f"; {directories_tightened} directory(ies) to 0700"
    if symlinks:
        summary += f"; skipped {len(symlinks)} symlink(s)"
    if failed:
        summary += f"; {len(failed)} could not be changed"
    print(summary + ".")

    remote_ok = 0
    remote_failed = 0
    for name, endpoint in sorted(get_endpoints(cfg).items()):
        # The remote copy session-sync seeded takes the remote umask; without
        # --remote this command reaches local files only, so say what to run.
        ip = endpoint.get("ip_address", {}).get("primary_ip") or ""
        user = endpoint.get("username", "")
        host = f"{user}@{ip}" if user and ip else ip
        paths = [endpoint.get("path", ""), endpoint.get("full_path", "")]
        for remote_path in filter(None, paths):
            quoted = shlex.quote(remote_path)
            shown_host = host or f"{user or '<user>'}@<host>"
            command = f"ssh {shown_host} chmod 600 {quoted}"
            if not remote:
                print(
                    f"ℹ️  Remote copy on '{name}' is not reached from here; run: {command}"
                )
                continue
            label = f"Remote '{name}' {shown_host}:{remote_path}"
            if not ip:
                remote_failed += 1
                print(f"❌ {label}: no address configured for this endpoint")
                continue
            if dry_run:
                print(f"🔍 {label}: would run {command}")
                continue
            reason = _remote_chmod(host, quoted)
            if reason is None:
                remote_ok += 1
                print(f"✅ {label} -> 0600")
                logger.info("fix-perms: remote %s %s -> 0600", name, remote_path)
            else:
                remote_failed += 1
                print(f"❌ {label}: {reason}")
                logger.warning(
                    "fix-perms: remote %s %s not changed: %s", name, remote_path, reason
                )
    if remote and not dry_run and (remote_ok or remote_failed):
        line = f"✅ Tightened {remote_ok} remote cop{'y' if remote_ok == 1 else 'ies'}"
        if remote_failed:
            line += (
                f"; {remote_failed} remote cop{'y' if remote_failed == 1 else 'ies'} "
                "could not be changed"
            )
        print(line + ".")
    return 1 if failed or remote_failed else 0


def _remote_chmod(host: str, quoted_path: str) -> str | None:
    """Run ``chmod 600`` on one remote copy; None on success, else a short reason.

    List argv, no shell. ssh joins the remote words with spaces for the remote
    shell, so the path arrives already quoted (the same ``shlex.quote`` the
    printed hint uses). ``BatchMode=yes`` turns any prompt into a refusal
    instead of a hang; the connect and overall timeouts bound an unreachable
    host. The reason classifies ssh's own exit (255) apart from chmod's, and
    carries the first stderr line so the learner sees what the host said.
    """
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        host,
        "chmod",
        "600",
        quoted_path,
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "timeout (no answer within 30s)"
    except FileNotFoundError:
        return "ssh not found on this machine"
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    first = detail[0] if detail else ""
    lowered = first.lower()
    if result.returncode == 255:
        # ssh itself failed: it never ran chmod.
        kind = (
            "permission"
            if "permission denied" in lowered
            else "unreachable"
            if any(
                word in lowered
                for word in (
                    "connection refused",
                    "timed out",
                    "no route",
                    "could not resolve",
                    "network is unreachable",
                    "host key verification failed",
                )
            )
            else "unreachable"
        )
    elif "permission denied" in lowered or "operation not permitted" in lowered:
        kind = "permission"
    elif "no such file" in lowered:
        kind = "missing"
    else:
        kind = f"failed (exit {result.returncode})"
    return f"{kind}: {first}" if first else kind


# A session's age is its newest known timestamp. updated_at is NULL for every
# Kiro v1 conversation (exporters/kiro.py) and for any harness that gave none;
# such a session is of unknown age, never "older than N days", so delete and
# archive keep it and say so (F-AST-06).
_SESSION_AGE_SQL = """COALESCE(
    s.updated_at,
    s.created_at,
    (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = s.id)
)"""


def _sessions_older_than(conn: sqlite3.Connection, cutoff: str) -> list[sqlite3.Row]:
    """Sessions whose age is known and before cutoff; report the undated ones."""
    undated = conn.execute(
        f"SELECT COUNT(*) FROM sessions s WHERE {_SESSION_AGE_SQL} IS NULL"
    ).fetchone()[0]
    if undated:
        print(f"ℹ️  Kept {undated} session(s) with no timestamp: their age is unknown.")
    return conn.execute(
        f"SELECT s.id, s.project_path, s.updated_at FROM sessions s "
        f"WHERE {_SESSION_AGE_SQL} < ?",
        (cutoff,),
    ).fetchall()


def _has_lifecycle(conn: sqlite3.Connection) -> bool:
    """True for a current-schema database (tombstones, record ownership)."""
    return conn.execute("PRAGMA user_version").fetchone()[0] >= 41


def _fts_without_delete_trigger(conn: sqlite3.Connection) -> bool:
    """True when ``messages_fts`` exists but nothing unindexes a deleted message.

    Migration v5 installs ``messages_fts_delete``; a database older than that
    has the index and no trigger, so whoever deletes a message must remove
    its index row too (D#7).
    """
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE name IN ('messages_fts', 'messages_fts_delete')"
        )
    }
    return "messages_fts" in names and "messages_fts_delete" not in names


def _without_learner_anchors(
    conn: sqlite3.Connection, sessions: list[sqlite3.Row]
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """Split sessions into (deletable, anchored): anchored ones own learner records.

    A permanent delete writes a tombstone, and a tombstone forgets every
    learner record its session owns (study sessions, teach-backs, parked
    topics, notes). Prune never evicts such a session
    (tiering._anchored_session_ids); an age-based delete keeps it too rather
    than erase learner progress, unless the caller asked for exactly that
    (``delete --forget-learner-records``, D5).
    """
    from agent_session_tools.tiering import _anchored_session_ids

    anchored = _anchored_session_ids(conn)
    return (
        [s for s in sessions if s["id"] not in anchored],
        [s for s in sessions if s["id"] in anchored],
    )


def _learner_records(
    conn: sqlite3.Connection, session_ids: list[str]
) -> dict[str, int]:
    """Learner rows ``purge_session`` destroys for these sessions, counted by table.

    Uses the purge's own selection (lifecycle.selected_records) so the count
    names exactly what the purge deletes, SET NULL tables included: the purge
    deletes those rows explicitly rather than letting the foreign key detach
    them. A row reachable from two of the sessions is counted once. The
    selection writes only TEMP tables; the caller commits before it changes
    pragmas or opens its own transaction.
    """
    from agent_session_tools.context.lifecycle import selected_records

    rows: set[tuple[str, str]] = set()
    for session_id in session_ids:
        with selected_records(conn, session_id) as selected:
            rows.update(
                (r[0], r[1])
                for r in conn.execute(f"SELECT table_name, row_id FROM {selected}")
            )
    counts: dict[str, int] = {}
    for table, _ in rows:
        counts[table] = counts.get(table, 0) + 1
    return dict(sorted(counts.items()))


def _describe_records(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    detail = ", ".join(f"{table}: {n}" for table, n in counts.items())
    return f"{total} learner record(s)" + (f" ({detail})" if detail else "")


def _archivable(
    conn: sqlite3.Connection, sessions: list[sqlite3.Row]
) -> list[sqlite3.Row]:
    """Drop sessions with rows the two-table archive cannot hold (F-AST-02).

    The archive database holds sessions and messages only. Archiving a
    session that also has notes, tags, file references, evidence, project
    ownership or learner records deleted it from the source with foreign
    keys off, orphaning those rows there while the archive never received
    them. Such a session now stays in the source. Derived rows (embeddings,
    the FTS index) do not hold a session back: triggers remove them.
    """
    from agent_session_tools.tiering import (
        _DERIVED_TABLES,
        _anchored_session_ids,
        _dependent_tables,
    )

    blocked = _anchored_session_ids(conn)
    for table, column in _dependent_tables(conn, "sessions"):
        blocked.update(
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL"
            )
        )
    for table, column in _dependent_tables(conn, "messages"):
        if table in _DERIVED_TABLES:
            continue
        blocked.update(
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT m.session_id FROM {table} c "
                f"JOIN messages m ON m.id = c.{column}"
            )
        )
    kept = sum(1 for s in sessions if s["id"] in blocked)
    if kept:
        print(
            f"ℹ️  Kept {kept} session(s) with rows the archive cannot hold (notes, "
            "tags, file references, evidence or learner records). 'session-maint "
            "sync-full' then 'session-maint prune' moves whole sessions out of "
            "the hot database instead."
        )
    return [s for s in sessions if s["id"] not in blocked]


def _backup_refused(db_path: Path) -> int:
    """Report that a requested backup was not made; the caller returns 1.

    create_backup returns None when it refuses (the backup_max_mb size
    guard). A command whose backup was requested then changes nothing, the
    same rule sync.py's pull follows (F-AST-03).
    """
    print(
        "❌ The requested backup was not made (see above), so nothing was "
        "changed. Snapshot the database ('session-maint snapshot') and re-run "
        "with --no-backup."
    )
    logger.error("requested backup of %s was refused; operation aborted", db_path)
    return 1


def _vacuum(db_path: Path, backup: bool = True) -> int:
    """Optimize database and reclaim unused space."""
    print(f"\n{'=' * 50}")
    print("DATABASE VACUUM (OPTIMIZE)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    # Get initial size
    initial_size = db_path.stat().st_size / (1024 * 1024)
    print(f"Initial size: {initial_size:.2f} MB")

    if backup and create_backup(db_path) is None:
        return _backup_refused(db_path)

    try:
        conn = sqlite3.connect(db_path)
        print("\n🔧 Running VACUUM...")
        conn.execute("VACUUM")
        conn.close()

        # Get final size
        final_size = db_path.stat().st_size / (1024 * 1024)
        saved = initial_size - final_size

        print(f"Final size: {final_size:.2f} MB")
        print(f"Space reclaimed: {saved:.2f} MB ({(saved / initial_size * 100):.1f}%)")
        print("✅ VACUUM completed successfully")

        logger.info(
            f"VACUUM completed: {initial_size:.2f}MB -> {final_size:.2f}MB, saved {saved:.2f}MB"
        )
        return 0

    except Exception as e:
        print(f"❌ VACUUM failed: {e}")
        logger.error(f"VACUUM failed: {e}")
        return 1


def _schema(db_path: Path, detailed: bool = False) -> int:
    """Display database schema (tables, columns, indexes)."""
    print(f"\n{'=' * 50}")
    print("DATABASE SCHEMA")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get all tables
        tables = conn.execute(
            """
            SELECT name, type FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
        """
        ).fetchall()

        for table in tables:
            table_name = table["name"]
            table_type = table["type"].upper()

            print(f"\n📊 {table_type}: {table_name}")
            print("-" * 50)

            # Get columns
            columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            print("Columns:")
            for col in columns:
                pk = " [PRIMARY KEY]" if col["pk"] else ""
                notnull = " NOT NULL" if col["notnull"] else ""
                default = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] else ""
                print(f"  • {col['name']}: {col['type']}{pk}{notnull}{default}")

            # Get indexes
            indexes = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%'
            """,
                (table_name,),
            ).fetchall()

            if indexes:
                print("Indexes:")
                for idx in indexes:
                    print(f"  • {idx['name']}")

            # Get row count
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
            print(f"Rows: {count['cnt']:,}")

            # Get table size (approximate)
            if detailed:
                size = conn.execute(
                    """
                    SELECT SUM(pgsize) as size FROM dbstat WHERE name=?
                """,
                    (table_name,),
                ).fetchone()
                if size["size"]:
                    size_mb = size["size"] / (1024 * 1024)
                    print(f"Size: {size_mb:.2f} MB")

        # Summary
        total_tables = len([t for t in tables if t["type"] == "table"])
        total_views = len([t for t in tables if t["type"] == "view"])

        print(f"\n{'=' * 50}")
        print(f"Summary: {total_tables} tables, {total_views} views")
        print(f"{'=' * 50}\n")

        conn.close()
        return 0

    except Exception as e:
        print(f"❌ Schema inspection failed: {e}")
        logger.error(f"Schema inspection failed: {e}")
        return 1


def _reindex(db_path: Path, backup: bool = True) -> int:
    """Rebuild full-text search index from the messages table."""
    print(f"\n{'=' * 50}")
    print("REBUILD FTS INDEX")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    if backup and create_backup(db_path) is None:
        return _backup_refused(db_path)

    try:
        from agent_session_tools.tiering import fts_integrity, repair_fts

        conn = sqlite3.connect(db_path)

        before = fts_integrity(conn)
        if not before.healthy:
            print(
                f"⚠️  FTS drift detected: {before.fts_rows:,} index rows for "
                f"{before.messages_with_content:,} messages "
                f"(drift {before.drift:+,})"
            )
        print("🔧 Rebuilding messages_fts index from messages table...")
        # NOTE: FTS5's built-in ('rebuild') command rebuilds from the FTS
        # table's OWN content store, so it preserves duplicated rows. A
        # drifted index must be cleared and repopulated from messages —
        # repair_fts does exactly that.
        after = repair_fts(conn)

        conn.commit()
        conn.close()

        print(f"✅ FTS index rebuilt successfully ({after.fts_rows:,} entries)")
        logger.info(f"FTS index rebuilt: {after.fts_rows} entries")
        return 0

    except Exception as e:
        print(f"❌ Reindex failed: {e}")
        logger.error(f"Reindex failed: {e}")
        return 1


# D4 (council pass 3): the two-table file `archive` writes has no reader, and
# the schema it hand-writes drifts from the canonical one. The supported path
# differs in what it moves and what it checks, so the notice says how rather
# than calling it a replacement. The removal is stated relative to the release
# that carries this deprecation (ADR-0016: deprecate now, remove one release
# later), never as a version number the next release may not have.
_ARCHIVE_DEPRECATION = (
    "⚠️  'session-maint archive' is deprecated and will be removed in the release "
    "after the one that deprecates it.\n"
    "   Use 'session-maint sync-full' then 'session-maint prune' instead (both "
    "need database.full_db_path set).\n"
    "   That is not a drop-in replacement. sync-full copies whole sessions "
    "(every column, every message,\n"
    "   file references) into the full database, which has the same schema as "
    "this one; prune then removes\n"
    "   from this database only the sessions it has verified there, keeps any "
    "session that owns learner\n"
    "   records, and is a dry run until --no-dry-run. This command copies "
    "sessions and messages only,\n"
    "   into a two-table file that nothing in StudyLoop reads."
)


def _archive(db_path: Path, days: int, backup: bool = True) -> int:
    """Archive sessions older than N days to separate database (deprecated, D4)."""
    print(_ARCHIVE_DEPRECATION)
    print(f"\n{'=' * 50}")
    print(f"ARCHIVE SESSIONS (older than {days} days)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    archive_path = db_path.parent / f"{db_path.stem}_archive.db"
    # R-20: sessions.updated_at is sourced from UTC transcript timestamps
    # (exporters/claude.py, exporters/codex.py). A naive datetime.now() cutoff
    # reads the *local* wall clock, which shifts the effective boundary by the
    # machine's UTC offset -- east of UTC, sessions updated within the last
    # offset-hours could wrongly satisfy `updated_at < cutoff_date`.
    cutoff_date = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    try:
        # Source database
        source_conn = sqlite3.connect(db_path)
        source_conn.row_factory = sqlite3.Row

        old_sessions = _archivable(
            source_conn, _sessions_older_than(source_conn, cutoff_date)
        )

        if not old_sessions:
            print(f"✅ No sessions older than {days} days found")
            source_conn.close()
            return 0

        print(f"Found {len(old_sessions)} sessions to archive")
        print(f"Cutoff date: {cutoff_date}")

        if backup and create_backup(db_path) is None:
            source_conn.close()
            return _backup_refused(db_path)

        # Create archive database if needed
        if not archive_path.exists():
            print(f"\n📦 Creating archive database: {archive_path}")
            _create_owner_only(archive_path)
            archive_conn = sqlite3.connect(archive_path)

            # Create tables manually (proper schema — must match live schema after all migrations)
            archive_conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    project_path TEXT,
                    git_branch TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata JSON,
                    content_hash TEXT,
                    import_fingerprint TEXT,
                    session_type TEXT DEFAULT 'work'
                )
            """
            )
            archive_conn.execute(
                """
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT,
                    model TEXT,
                    timestamp TEXT,
                    metadata JSON,
                    content_hash TEXT,
                    seq INTEGER,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """
            )
            # Create indexes
            archive_conn.execute(
                "CREATE INDEX idx_messages_session ON messages(session_id)"
            )
            archive_conn.execute(
                "CREATE INDEX idx_messages_timestamp ON messages(timestamp)"
            )
            archive_conn.execute("CREATE INDEX idx_sessions_source ON sessions(source)")
            archive_conn.execute(
                "CREATE INDEX idx_sessions_project ON sessions(project_path)"
            )

            # FTS table — matches v5 migration schema (porter stemming, unindexed metadata)
            archive_conn.execute(
                """
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    role UNINDEXED,
                    tokenize='porter unicode61'
                )
            """
            )

            archive_conn.commit()
        else:
            archive_conn = sqlite3.connect(archive_path)

        # Move sessions and messages
        session_ids = [s["id"] for s in old_sessions]
        archived_count = 0
        message_count = 0

        print("\n🔧 Archiving sessions...")
        for session_id in session_ids:
            # Copy session — explicit columns guard against positional drift
            session = source_conn.execute(
                """
                SELECT id, source, project_path, git_branch, created_at, updated_at,
                       metadata, content_hash, import_fingerprint, session_type
                FROM sessions WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

            if session:
                archive_conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                        (id, source, project_path, git_branch, created_at, updated_at,
                         metadata, content_hash, import_fingerprint, session_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    tuple(session),
                )
                archived_count += 1

            # Copy messages — explicit columns guard against positional drift
            messages = source_conn.execute(
                """
                SELECT id, session_id, parent_id, role, content, model,
                       timestamp, metadata, content_hash, seq
                FROM messages WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()

            for msg in messages:
                archive_conn.execute(
                    """
                    INSERT OR REPLACE INTO messages
                        (id, session_id, parent_id, role, content, model,
                         timestamp, metadata, content_hash, seq)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    tuple(msg),
                )
                message_count += 1

            # Delete from source
            source_conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            source_conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        # Index this run's sessions in the archive's FTS table (no triggers in
        # the archive DB). Only this run's sessions: re-inserting rows an
        # earlier run indexed reuses their rowids, which FTS5 refuses, so the
        # second archive on a machine failed (F-AST-05). Clearing them first
        # also drops entries left by a session archived again (INSERT OR
        # REPLACE gives its messages new rowids).
        placeholders = ",".join("?" * len(session_ids))
        archive_conn.execute(
            f"DELETE FROM messages_fts WHERE session_id IN ({placeholders})",
            session_ids,
        )
        archive_conn.execute(
            f"""
            INSERT INTO messages_fts(rowid, content, session_id, role)
            SELECT m.rowid, m.content, m.session_id, m.role
            FROM messages m
            WHERE m.content IS NOT NULL AND m.session_id IN ({placeholders})
            """,
            session_ids,
        )

        archive_conn.commit()
        source_conn.commit()

        archive_conn.close()
        source_conn.close()

        print(f"✅ Archived {archived_count} sessions ({message_count} messages)")
        print(f"Archive location: {archive_path}")

        logger.info(f"Archived {archived_count} sessions to {archive_path}")
        return 0

    except Exception as e:
        print(f"❌ Archive failed: {e}")
        logger.error(f"Archive failed: {e}")
        return 1


def _delete_old(
    db_path: Path,
    days: int,
    confirm: bool = False,
    backup: bool = True,
    forget_learner_records: bool = False,
    allow_unmigrated: bool = False,
) -> int:
    """Delete sessions older than N days (requires confirmation).

    Sessions that own learner records are kept and counted in the summary;
    ``forget_learner_records`` destroys them and those records through
    ``purge_session`` instead (D5, council pass 3).

    A pre-lifecycle schema (``user_version < 41``) records no tombstone, so
    a session deleted there is re-imported by the next export from its native
    transcript (F-AST-04). Such a database is refused with the migration
    named; ``allow_unmigrated`` runs the pre-lifecycle delete anyway, with a
    warning (plan 4, item 7).
    """
    print(f"\n{'=' * 50}")
    print(f"⚠️  DELETE SESSIONS (older than {days} days)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    # R-20: see the matching comment in `_archive` -- this cutoff feeds an
    # irreversible DELETE, so the naive-local-time skew is the higher-stakes
    # half of D2.
    cutoff_date = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        lifecycle = _has_lifecycle(conn)
        if forget_learner_records and not lifecycle:
            # Destroying learner records is only ever done by purge_session,
            # which needs the lifecycle schema; there is no bare-DELETE
            # fallback for it. Checked first: --allow-unmigrated does not
            # unlock it.
            import shlex

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.close()
            print(
                "❌ --forget-learner-records needs the current schema (version 41 "
                f"or later, which records tombstones); this database is at version "
                f"{version}. Nothing was changed. Migrate it first (for example "
                f"'session-maint embed-check --db {shlex.quote(str(db_path))}' "
                "migrates before it audits), then delete again."
            )
            return 1
        if not lifecycle:
            import shlex

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            migrate_hint = (
                f"'session-maint embed-check --db {shlex.quote(str(db_path))}' "
                "migrates before it audits"
            )
            if not allow_unmigrated:
                conn.close()
                print(
                    f"❌ This database is at schema version {version}; delete needs "
                    "version 41 or later, which records a tombstone for every "
                    "deleted session so the next export cannot re-import it from "
                    "its native transcript. Nothing was changed. Migrate it first "
                    f"(for example {migrate_hint}), then delete again -- or pass "
                    "--allow-unmigrated to delete without tombstones."
                )
                return 1
            print(
                f"⚠️  --allow-unmigrated: schema version {version} records no "
                "tombstone, so the next export can re-import every session deleted "
                f"here from its native transcript. Migrate ({migrate_hint}) to make "
                "a deletion stick."
            )

        old_sessions = _sessions_older_than(conn, cutoff_date)
        anchored: list[sqlite3.Row] = []
        if lifecycle:
            old_sessions, anchored = _without_learner_anchors(conn, old_sessions)
            if forget_learner_records:
                old_sessions += anchored
            elif anchored:
                print(
                    f"ℹ️  Kept {len(anchored)} session(s) that own learner records "
                    "(study sessions, teach-backs, parked topics, notes). "
                    "--forget-learner-records deletes them and those records."
                )
        kept = 0 if forget_learner_records else len(anchored)

        if not old_sessions:
            if kept:
                print(
                    f"✅ Deleted 0 session(s); kept {kept} that own learner records "
                    "(--forget-learner-records deletes them)."
                )
            else:
                print(f"✅ No sessions older than {days} days found")
            conn.close()
            return 0

        # Count messages
        session_ids = [s["id"] for s in old_sessions]
        placeholders = ",".join("?" * len(session_ids))
        message_count = conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()[0]

        print(f"Found {len(old_sessions)} sessions ({message_count} messages)")
        print(f"Cutoff date: {cutoff_date}")
        if forget_learner_records and anchored:
            would = _learner_records(conn, [s["id"] for s in anchored])
            conn.commit()  # end the TEMP-table selection before any pragma
            print(
                f"⚠️  --forget-learner-records: {len(anchored)} of them own learner "
                f"records. Would destroy {_describe_records(would)}."
            )
        print("\n⚠️  THIS OPERATION CANNOT BE UNDONE!")

        if not confirm:
            print("\n❌ Operation cancelled. Use --confirm to proceed.")
            conn.close()
            return 1

        if backup and create_backup(db_path) is None:
            conn.close()
            return _backup_refused(db_path)

        destroyed: dict[str, int] = {}
        if lifecycle:
            # Permanent means permanent (F-AST-04): purge_session writes a
            # context_tombstones row, which the exporters honour, so the next
            # export cannot re-import the session from its native transcript.
            # It also removes every dependent row (notes, tags, file
            # references, evidence, ownership) that a bare DELETE with foreign
            # keys off left orphaned (F-AST-02), and with
            # --forget-learner-records the session's learner records (D5).
            from agent_session_tools.context.lifecycle import purge_session

            print("\n🗑️  Deleting sessions (tombstoned against re-import)...")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if forget_learner_records and anchored:
                    # Counted inside the write transaction: exactly what goes.
                    destroyed = _learner_records(conn, [s["id"] for s in anchored])
                for session_id in session_ids:
                    purge_session(conn, session_id, permanent=True)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        else:
            # Pre-lifecycle schema (user_version < 41): no tombstones exist to
            # write and purge_session's closure is not available, so this used
            # to be a bare DELETE with foreign keys off that orphaned every
            # dependent row (notes, tags, file references, embeddings,
            # ownership bindings). Now foreign keys are on and each session is
            # deleted children-first in its own savepoint: what the schema
            # declares ON DELETE CASCADE goes with it, and a dependent it does
            # not cascade makes SQLite refuse, so that session is rolled back
            # whole and kept. Sessions that own learner records are kept
            # without trying, as on the lifecycle path (a cascade would take
            # their ownership bindings). Migrating first gives the full
            # lifecycle delete; the message below says how.
            from agent_session_tools.tiering import _anchored_session_ids

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            anchored_ids = _anchored_session_ids(conn)
            # Before schema v5 there is no messages_fts_delete trigger, so a
            # deleted message kept its index row: a search still found the
            # deleted session and fts-check reported drift (D#7). The index
            # rows are removed here by rowid, inside the session's savepoint,
            # before the messages go (an external-content index needs the
            # row to still exist to unindex it); rowid is the one thing every
            # FTS shape shares, so no column of the old table is assumed.
            clean_fts = _fts_without_delete_trigger(conn)
            deleted = deleted_messages = kept = 0
            print("\n🗑️  Deleting sessions (dependents first, foreign keys on)...")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for session_id in session_ids:
                    if session_id in anchored_ids:
                        kept += 1
                        continue
                    conn.execute("SAVEPOINT pre_lifecycle_delete")
                    try:
                        if clean_fts:
                            conn.execute(
                                "DELETE FROM messages_fts WHERE rowid IN "
                                "(SELECT rowid FROM messages WHERE session_id = ?)",
                                (session_id,),
                            )
                        removed = conn.execute(
                            "DELETE FROM messages WHERE session_id = ?", (session_id,)
                        ).rowcount
                        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                    except sqlite3.IntegrityError:
                        conn.execute("ROLLBACK TO pre_lifecycle_delete")
                        kept += 1
                    else:
                        deleted += 1
                        deleted_messages += removed
                    finally:
                        conn.execute("RELEASE pre_lifecycle_delete")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            conn.close()
            if kept:
                import shlex

                print(
                    f"ℹ️  Kept {kept} session(s) that own learner records or rows this "
                    f"schema (v{version}) does not delete with them. Run "
                    f"'session-repair --apply --db {shlex.quote(str(db_path))}' to "
                    "migrate the database, then delete again."
                )
            print(f"✅ Deleted {deleted} sessions ({deleted_messages} messages)")
            logger.info(f"Deleted {deleted} old sessions (pre-lifecycle schema)")
            return 0
        conn.close()

        if destroyed:
            print(f"🗑️  Destroyed {_describe_records(destroyed)}.")
        summary = (
            f"✅ Deleted {len(old_sessions)} session(s) ({message_count} messages)"
        )
        if forget_learner_records and anchored:
            summary += f", including {len(anchored)} that owned learner records"
        elif kept:
            summary += (
                f"; kept {kept} that own learner records "
                "(--forget-learner-records deletes them)"
            )
        print(summary + ".")
        logger.info(
            "Deleted %d old sessions (%d owned learner records); kept %d",
            len(old_sessions),
            len(anchored) if forget_learner_records else 0,
            kept,
        )
        return 0

    except Exception as e:
        print(f"❌ Delete failed: {e}")
        logger.error(f"Delete failed: {e}")
        return 1


def _handle_duplicates(
    db_path: Path,
    threshold: float = 0.8,
    auto_merge: bool = False,
    merge_ids: list[str] | None = None,
) -> int:
    """Handle deduplication commands."""
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    from .context.records import connect
    from .context.scope import ScopeError
    from .deduplication import ProtectedMergeError

    conn = connect(db_path)

    try:
        if merge_ids:
            # Manual merge specific sessions
            primary_id = merge_ids[0]
            duplicate_ids = merge_ids[1:]

            print(f"🔄 Merging {len(duplicate_ids)} sessions into {primary_id[:20]}...")
            stats = merge_duplicates(conn, primary_id, duplicate_ids)
            print(
                f"✅ Merged: {stats['messages_moved']} messages moved, "
                f"{stats['sessions_removed']} sessions removed"
            )

        elif auto_merge:
            # Auto-merge high similarity duplicates
            print("🔍 Finding high-similarity duplicates for auto-merge...")
            stats = auto_merge_safe_duplicates(conn, min_similarity=0.95)

            if stats["groups_merged"] > 0:
                print(f"✅ Auto-merged {stats['groups_merged']} duplicate groups")
                print(
                    f"   {stats['messages_moved']} messages moved, "
                    f"{stats['sessions_removed']} sessions removed"
                )
            if stats.get("groups_protected", 0):
                print(
                    f"Retained {stats['groups_protected']} protected groups; source identities cannot be merged"
                )
            elif not stats["groups_merged"]:
                print("✅ No high-similarity duplicates found")

        else:
            # List duplicates for review
            print(f"🔍 Scanning for duplicates (threshold: {threshold:.1%})...")
            list_all_duplicates(conn, threshold)

    except (ScopeError, ProtectedMergeError, ValueError) as exc:
        print(f"Duplicate operation refused: {exc}")
        return 1
    finally:
        conn.close()

    return 0


# ==================== CLI Commands ====================


@app.command()
def vacuum(
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Optimize database and reclaim unused space."""
    db_path = db if db else _get_db_path()
    exit_code = _vacuum(db_path, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command()
def schema(
    db: Annotated[Path | None, db_option] = None,
    detailed: Annotated[
        bool, typer.Option("--detailed", help="Show detailed info including sizes")
    ] = False,
) -> None:
    """Display database schema (tables, columns, indexes)."""
    db_path = db if db else _get_db_path()
    exit_code = _schema(db_path, detailed)
    raise typer.Exit(exit_code)


@app.command()
def reindex(
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Rebuild full-text search index."""
    db_path = db if db else _get_db_path()
    exit_code = _reindex(db_path, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command(deprecated=True)
def archive(
    days: Annotated[
        int, typer.Option("--days", help="Archive sessions older than N days")
    ],
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Archive old sessions to a separate two-table database.

    Deprecated; removed in the release after the one that deprecates it. Use
    'session-maint sync-full' then 'session-maint prune', which move whole
    sessions and verify them first.
    """
    db_path = db if db else _get_db_path()
    exit_code = _archive(db_path, days, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command("delete")
def delete_cmd(
    days: Annotated[
        int,
        typer.Option(
            "--days",
            help=(
                "Delete sessions older than N days. Sessions that own learner "
                "records (study sessions, teach-backs, parked topics, notes) are "
                "kept unless --forget-learner-records is given."
            ),
        ),
    ],
    db: Annotated[Path | None, db_option] = None,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirm deletion (required)")
    ] = False,
    no_backup: Annotated[bool, no_backup_option] = False,
    forget_learner_records: Annotated[
        bool,
        typer.Option(
            "--forget-learner-records",
            help=(
                "Also delete old sessions that own learner records, destroying "
                "those records (tombstoned, listed by table). Still needs --confirm."
            ),
        ),
    ] = False,
    allow_unmigrated: Annotated[
        bool,
        typer.Option(
            "--allow-unmigrated",
            help=(
                "Delete on a database older than schema 41 anyway. Such a schema "
                "records no tombstone, so the next export re-imports what was "
                "deleted; without this flag the command refuses and names the "
                "migration."
            ),
        ),
    ] = False,
) -> None:
    """Delete old sessions permanently (requires --confirm).

    Sessions that own learner records are kept and counted in the summary
    unless --forget-learner-records is given. A database older than schema
    41 is refused unless --allow-unmigrated is given.
    """
    db_path = db if db else _get_db_path()
    exit_code = _delete_old(
        db_path,
        days,
        confirm,
        backup=not no_backup,
        forget_learner_records=forget_learner_records,
        allow_unmigrated=allow_unmigrated,
    )
    raise typer.Exit(exit_code)


@app.command("find-duplicates")
def find_duplicates(
    db: Annotated[Path | None, db_option] = None,
    threshold: Annotated[
        float, typer.Option("--threshold", help="Similarity threshold (0.0-1.0)")
    ] = 0.8,
    auto_merge: Annotated[
        bool,
        typer.Option(
            "--auto-merge", help="Auto-merge high similarity duplicates (>95%)"
        ),
    ] = False,
    merge_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--merge-ids", help="Manually merge specific session IDs into first ID"
        ),
    ] = None,
) -> None:
    """Find and manage duplicate sessions."""
    db_path = db if db else _get_db_path()
    exit_code = _handle_duplicates(db_path, threshold, auto_merge, merge_ids)
    raise typer.Exit(exit_code)


# ==================== Tiering Commands ====================


@app.command("fts-check")
def fts_check(
    db: Annotated[Path | None, db_option] = None,
    fix: Annotated[
        bool, typer.Option("--fix", help="Rebuild the index when drift is found")
    ] = False,
) -> None:
    """Check the FTS index invariant (one index row per message with content)."""
    from agent_session_tools.tiering import fts_integrity, repair_fts

    db_path = db if db else _get_db_path()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        raise typer.Exit(1)

    conn = sqlite3.connect(db_path)
    try:
        result = fts_integrity(conn)
        if result.healthy:
            print(
                f"✅ FTS index consistent: {result.fts_rows:,} rows for "
                f"{result.messages_with_content:,} messages"
            )
            raise typer.Exit(0)

        print(
            f"⚠️  FTS drift: {result.fts_rows:,} index rows for "
            f"{result.messages_with_content:,} messages (drift {result.drift:+,})"
        )
        if not fix:
            print("   Run with --fix to rebuild the index from the messages table.")
            raise typer.Exit(1)

        print("🔧 Rebuilding index...")
        after = repair_fts(conn)
        conn.commit()
        print(f"✅ Rebuilt: {after.fts_rows:,} entries (drift now {after.drift:+,})")
        raise typer.Exit(0 if after.healthy else 1)
    finally:
        conn.close()


@app.command("fix-perms")
def fix_perms(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List the files that would change; chmod none"),
    ] = False,
    remote: Annotated[
        bool,
        typer.Option(
            "--remote",
            help=(
                "Also run `ssh <endpoint> chmod 600 <remote db>` for every configured "
                "sync endpoint (BatchMode, 10s connect / 30s total per host); one result "
                "row per endpoint, a failed host never stops the sweep. Off by default: "
                "the commands are only printed."
            ),
        ),
    ] = False,
) -> None:
    """Make existing snapshot, backup and sidecar files owner-only (0600).

    Copies of the session record made before they were created owner-only
    keep the mode the umask gave them. Sweeps only the files the config
    names: <stem>_backup_*.db in database.backup_dir, <stem>_snapshot_*.db in
    database.snapshot_dir (or backup_dir), and the <stem>.vec.db sidecar
    beside the hot and the full database. Reports counts; never creates,
    moves or follows a symlink. Remote copies seeded by session-sync are
    printed as the ssh command to run; --remote runs it.
    """
    raise typer.Exit(_fix_perms(_get_config(), dry_run=dry_run, remote=remote))


@app.command()
def compact(
    source: Annotated[Path, typer.Argument(help="Bloated source database (read-only)")],
    dest: Annotated[Path, typer.Argument(help="Destination for the clean database")],
) -> None:
    """Rescue a bloated database into a fresh one (rebuilds FTS exactly once).

    The source is opened read-only and never modified. Refuses to overwrite
    an existing destination.
    """
    from agent_session_tools.tiering import compact_database

    print(f"\n{'=' * 50}")
    print("COMPACT DATABASE")
    print(f"{'=' * 50}")
    try:
        stats = compact_database(source, dest)
    except (FileNotFoundError, FileExistsError) as exc:
        print(f"❌ {exc}")
        raise typer.Exit(1) from exc

    print(
        f"Source: {stats.source_size_mb:,.1f} MB -> Dest: {stats.dest_size_mb:,.1f} MB"
    )
    for table, rows in sorted(stats.tables_copied.items()):
        print(f"  • {table}: {rows:,} rows")
    if stats.fts:
        status = (
            "✅ consistent" if stats.fts.healthy else f"⚠️ drift {stats.fts.drift:+,}"
        )
        print(f"FTS index: {stats.fts.fts_rows:,} rows ({status})")
    print(f"✅ Compacted database written: {dest}")


@app.command("sync-full")
def sync_full(
    db: Annotated[Path | None, db_option] = None,
    quiet: Annotated[bool, typer.Option("--quiet", help="Suppress output")] = False,
) -> None:
    """Incrementally sync the hot DB into the configured full DB (idempotent)."""
    from agent_session_tools.tiering import (
        acquire_sync_lock,
        release_sync_lock,
        sync_to_full,
        write_sync_marker,
    )

    if not acquire_sync_lock():
        if not quiet:
            print("⏳ Another sync is already running — skipping.")
        raise typer.Exit(0)
    try:
        stats = sync_to_full(hot=db)
        write_sync_marker()
        if not quiet:
            print(
                f"✅ Synced {stats.sessions_synced} session(s) "
                f"({stats.messages_synced} messages) — "
                f"full DB holds {stats.sessions_total_full:,} sessions"
            )
        # Periodic point-in-time protection for the record itself.
        from agent_session_tools.tiering import maybe_snapshot

        snap = maybe_snapshot()
        if snap and not quiet:
            print(f"📸 Auto-snapshot created: {snap}")
    except (ValueError, FileNotFoundError, LegacySyncRefused) as exc:
        if not quiet:
            print(f"❌ {exc}")
        logger.warning("sync-full skipped: %s", exc)
        raise typer.Exit(1) from exc
    finally:
        release_sync_lock()


@app.command()
def snapshot(
    retain: Annotated[
        int | None,
        typer.Option("--retain", help="Snapshots to keep (default: from config)"),
    ] = None,
) -> None:
    """Create a point-in-time snapshot of the full DB, rotating old snapshots."""
    from agent_session_tools.tiering import create_snapshot

    try:
        path = create_snapshot(retain=retain)
    except (ValueError, FileNotFoundError, LegacySyncRefused) as exc:
        print(f"❌ {exc}")
        raise typer.Exit(1) from exc
    print(f"✅ Snapshot created: {path}")


@app.command()
def prune(
    days: Annotated[
        int, typer.Option("--days", help="Prune sessions older than N days")
    ] = 30,
    db: Annotated[Path | None, db_option] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Preview without deleting"),
    ] = True,
    no_vacuum: Annotated[
        bool, typer.Option("--no-vacuum", help="Skip VACUUM after prune")
    ] = False,
) -> None:
    """Prune old sessions from the hot DB — only those verified in the full DB.

    Runs in dry-run mode by default; pass --no-dry-run to actually delete.
    A session is only deleted when the full DB holds the same session with a
    matching content hash and at least as many messages. Learning tables are
    never touched.
    """
    from agent_session_tools.tiering import prune_hot

    print(f"\n{'=' * 50}")
    print(f"PRUNE HOT DB (older than {days} days){' — DRY RUN' if dry_run else ''}")
    print(f"{'=' * 50}")
    try:
        stats = prune_hot(days=days, hot=db, dry_run=dry_run, vacuum=not no_vacuum)
    except (ValueError, FileNotFoundError, LegacySyncRefused) as exc:
        print(f"❌ {exc}")
        raise typer.Exit(1) from exc

    print(f"Candidates older than {days} days: {stats.candidates}")
    print(f"Verified present in full DB:       {stats.verified}")
    if stats.skipped_anchored:
        print(f"Retained (own learner records):    {stats.skipped_anchored}")
    if stats.skipped_unverified:
        print(f"⚠️  Skipped (NOT in full DB):       {stats.skipped_unverified}")
        for sid in stats.skipped_ids[:5]:
            print(f"     - {sid}")
        if len(stats.skipped_ids) > 5:
            print(f"     ... and {len(stats.skipped_ids) - 5} more")
        print("   Run 'session-maint sync-full' to back them up first.")
    if dry_run:
        print(
            f"\nDry run: would delete {stats.verified} session(s) "
            f"({stats.messages_deleted:,} messages). "
            "Pass --no-dry-run to apply."
        )
    else:
        print(
            f"✅ Deleted {stats.sessions_deleted} session(s) "
            f"({stats.messages_deleted:,} messages), "
            f"reclaimed {stats.reclaimed_mb:.1f} MB"
        )


# ==================== Embedding Commands ====================


def _configured_embedding(model: str | None) -> tuple[str, int]:
    """``(model name, dim)`` from the registry -- reads config, never loads a model."""
    from agent_session_tools.embeddings import get_model_config

    if model is None:
        cfg = _get_config().get("semantic_search", {})
        import os

        model = os.getenv("EMBEDDING_MODEL") or cfg.get("model") or "all-mpnet-base-v2"
    return model, int(get_model_config(model)["dimensions"])


def _min_content_length() -> int:
    from agent_session_tools.embedding_alignment import DEFAULT_MIN_CONTENT_LENGTH

    cfg = _get_config().get("semantic_search", {})
    return int(cfg.get("min_content_length", DEFAULT_MIN_CONTENT_LENGTH))


def _print_alignment(report) -> None:
    print(
        f"Model {report.model} (dim {report.dim}) — {report.rows:,} vector row(s) for "
        f"{report.eligible:,} eligible message(s)"
    )
    print(f"  missing (backlog):  {report.missing:,}")
    print(f"  orphaned:           {report.orphaned:,}")
    print(f"  stale:              {report.stale:,}")
    print(f"  model_mismatch:     {report.model_mismatch:,}")
    print(f"  hidden:             {report.hidden:,}")


def _migrate_or_exit(conn: sqlite3.Connection) -> None:
    """Bring the schema current before touching migration 48's embedding tables.

    Every other entry point (``session-export``, scrub, the context store)
    migrates on open; without this, a database last written by an older release
    fails here with ``no such column: e.content_sha256``. A refused migration is
    an error line and exit 1 (D-8), never a traceback -- ``migrate`` has already
    rolled the whole sequence back, so the database is unchanged.
    """
    try:
        applied = migrate(conn)
    except RuntimeError as exc:
        print(f"❌ {exc}")
        raise typer.Exit(1) from exc
    if applied:
        print(f"Applied {len(applied)} database migration(s)")


@app.command("embed")
def embed_cmd(
    db: Annotated[Path | None, db_option] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Embedding model (default: from config)"),
    ] = None,
    budget_seconds: Annotated[
        float | None,
        typer.Option("--budget-seconds", help="Stop between batches after N seconds"),
    ] = None,
    batch_size: Annotated[
        int, typer.Option("--batch-size", help="Messages encoded per write transaction")
    ] = 64,
    replace_model: Annotated[
        bool,
        typer.Option(
            "--replace-model",
            help="Sweep vectors from another model/dimension first (they cannot be compared)",
        ),
    ] = False,
) -> None:
    """Embed the backlog of eligible messages, then reconcile the vector index."""
    from agent_session_tools import embedding_store
    from agent_session_tools.embeddings import is_available as embeddings_installed

    db_path = db if db else _get_db_path()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        raise typer.Exit(1)

    model_name, _dim = _configured_embedding(model)
    availability = embedding_store.availability(model_name)
    # D-8: a missing dependency is an install instruction and exit 1, never a
    # traceback and never a silent no-op. A cold model cache is different: this
    # command is the interactive path that is allowed to fetch it (the export
    # hook, D-7, is the path that must not).
    if not availability.extension_ok or not embeddings_installed():
        print(f"❌ Semantic layer not installed: {availability.reason}")
        if embedding_store.INSTALL_HINT not in availability.reason:
            print(f"   {embedding_store.INSTALL_HINT}")
        raise typer.Exit(1)
    if not availability.model_ok:
        print(f"⬇️  Model {model_name} is not in the local cache yet — fetching once...")

    conn = sqlite3.connect(db_path)
    try:
        _migrate_or_exit(conn)
        try:
            stats = embedding_store.embed(
                conn,
                model=model_name,
                budget_seconds=budget_seconds,
                batch_size=batch_size,
                replace_model=replace_model,
            )
        except ValueError as exc:  # model/dim mismatch without --replace-model
            print(f"❌ {exc}")
            raise typer.Exit(1) from exc
        except RuntimeError as exc:
            print(f"❌ {exc}")
            raise typer.Exit(1) from exc

        if stats.swept:
            print(f"🧹 Swept {stats.swept:,} vector(s) from another model/dimension")
        print(
            f"✅ Embedded {stats.embedded_messages:,} message(s) "
            f"({stats.chunks_written:,} chunk(s), {stats.truncated_chunks:,} hard-windowed) "
            f"with {stats.model} in {stats.seconds:.1f}s"
        )
        if stats.skipped_changed:
            print(
                f"↻  Skipped {stats.skipped_changed:,} message(s) rewritten mid-run "
                "— still in the backlog for the next run"
            )
        print(f"   Backlog remaining: {stats.remaining:,}")

        inserted, deleted = embedding_store.reconcile(conn)
        sidecar = embedding_store.sidecar_path(db_path)
        size_mb = sidecar.stat().st_size / (1024 * 1024) if sidecar.exists() else 0.0
        print(
            f"🧭 Vector index reconciled: +{inserted:,} / -{deleted:,} "
            f"({sidecar.name}, {size_mb:.1f} MB)"
        )
        logger.info(
            "embed: %d messages, %d chunks, %d skipped, %d remaining, %.1fs",
            stats.embedded_messages,
            stats.chunks_written,
            stats.skipped_changed,
            stats.remaining,
            stats.seconds,
        )
    finally:
        conn.close()
    raise typer.Exit(0)


@app.command("embed-check")
def embed_check(
    db: Annotated[Path | None, db_option] = None,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Sweep misaligned vectors and reconcile the index"),
    ] = False,
) -> None:
    """Check the embedding alignment invariants (orphaned / stale / model / hidden)."""
    from agent_session_tools import embedding_store
    from agent_session_tools.embedding_alignment import alignment_report, sweep

    db_path = db if db else _get_db_path()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        raise typer.Exit(1)

    model_name, dim = _configured_embedding(None)
    min_length = _min_content_length()
    conn = sqlite3.connect(db_path)
    try:
        _migrate_or_exit(conn)
        report = alignment_report(
            conn, model=model_name, dim=dim, min_content_length=min_length
        )
        _print_alignment(report)
        if report.complete:
            print("✅ Embeddings aligned and complete")
            raise typer.Exit(0)
        if report.aligned:
            # Only the embed job can shrink the backlog: it needs the model.
            print(f"✅ Embeddings aligned; {report.missing:,} still to embed")
            print("   Run 'session-maint embed' to work through the backlog.")
            raise typer.Exit(0)

        if not fix:
            print("⚠️  Misaligned vectors present. Run with --fix to sweep them.")
            raise typer.Exit(1)

        swept = sweep(conn, model=model_name, dim=dim)
        conn.commit()
        print(
            f"🧹 Swept {swept.deleted:,} vector(s): orphaned {swept.orphaned:,}, "
            f"stale {swept.stale:,}, model_mismatch {swept.model_mismatch:,}, "
            f"hidden {swept.hidden:,}"
        )
        try:
            inserted, deleted = embedding_store.reconcile(conn)
            print(f"🧭 Vector index reconciled: +{inserted:,} / -{deleted:,}")
        except (RuntimeError, ValueError) as exc:
            # The sidecar is derived: an unavailable extension leaves the record
            # correct and the index stale, which the next embed rebuilds.
            print(f"ℹ️  Vector index not reconciled ({exc}); the record is aligned.")

        after = alignment_report(
            conn, model=model_name, dim=dim, min_content_length=min_length
        )
        _print_alignment(after)
        raise typer.Exit(0 if after.aligned else 1)
    finally:
        conn.close()


# ==================== Query Encoder Artefact Commands ====================


@app.command("fetch-query-encoder")
def fetch_query_encoder(
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Embedding model (default: the database's pin, then config)",
        ),
    ] = None,
) -> None:
    """Fetch + verify the pinned ONNX query-encoder artefact (explicit action only).

    Downloads the pinned onnx/model.onnx, tokenizer.json and
    tokenizer_config.json at the exact revision recorded in
    embeddings.ONNX_ARTIFACTS, verifies each against its registered sha256
    (and, for the onnx graph, its pinned size), and reports what/where/size.

    Never runs from a search or the SessionEnd export hook -- this command
    and 'studyloop doctor --fix' are the only two callers. Exit codes
    distinguish the three non-failure outcomes (deliberately outside click's
    reserved 1/2 range -- see docs/cli-reference.md): 0 nothing needed
    fetching (already cached and verified), 3 fetched it just now, 4
    declined because HF_HUB_OFFLINE=1 is set; any other failure (unknown
    model, verification mismatch, missing dependency) exits 1.
    """
    from agent_session_tools.artefact_fetch import (
        EXIT_CODES,
        ArtefactVerificationError,
        fetch_query_encoder_artefact,
    )

    try:
        result = fetch_query_encoder_artefact(model)
    except (ValueError, ArtefactVerificationError, RuntimeError) as exc:
        print(f"❌ {exc}")
        raise typer.Exit(1) from exc

    if result.status == "offline_skip":
        print(f"⏭️  {result.detail}")
        raise typer.Exit(EXIT_CODES[result.status])

    verb = "Already cached" if result.status == "already_cached" else "Fetched"
    print(f"✅ {verb}: {result.hf_name}@{result.revision} (model: {result.model})")
    for f in result.files:
        print(f"   {f.relpath}: {f.size_bytes:,} bytes (sha256 verified) -> {f.path}")
    total_mb = result.total_bytes / (1024 * 1024)
    print(f"   total: {total_mb:.1f} MB")
    raise typer.Exit(EXIT_CODES[result.status])


# ==================== Main Entry Point ====================


def main() -> int:
    """CLI entry point for database maintenance."""
    app()
    return 0


if __name__ == "__main__":
    app()
