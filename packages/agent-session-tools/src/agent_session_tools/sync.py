#!/usr/bin/env python3
"""Sync sessions.db between machines.

Streams SQL deltas over SSH instead of copying entire database files.
Missing conversation fields are merged without deleting evidence-bearing rows.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agent_session_tools.config_loader import (
    get_backup_dir,
    get_db_path,
    get_endpoints,
    get_log_path,
    load_config,
)
from agent_session_tools.replication import legacy as legacy_guard

# Tables to sync (order matters — sessions before messages for FK)
# Session-scoped tables: filtered by session_id during delta sync
SYNC_TABLES = [
    "sessions",
    "messages",
    "sync_session_revisions",
    "session_notes",
    "session_tags",
    "session_learning_metadata",
    "file_references",
]

# Global tables: synced in full (small metadata, no session_id column)
GLOBAL_SYNC_TABLES = [
    "study_progress",
    "study_sessions",
    "teach_back_scores",
    "knowledge_bridges",
    "concepts",
    "concept_aliases",
    "concept_relations",
    "message_concepts",
    "parked_topics",
    "scrub_log",
]

TABLE_SYNC_COLUMNS = {
    "sessions": [
        "id",
        "source",
        "project_path",
        "git_branch",
        "created_at",
        "updated_at",
        "metadata",
    ],
    "messages": [
        "id",
        "session_id",
        "parent_id",
        "role",
        "content",
        "model",
        "timestamp",
        "metadata",
    ],
    "sync_session_revisions": ["session_id", "machine_id", "seq"],
    "session_notes": ["session_id", "notes", "updated_at"],
    "session_tags": ["session_id", "tag"],
    "session_learning_metadata": [
        "session_id",
        "topics",
        "concepts_practiced",
        "skill_gaps",
        "assessment_score",
        "notes",
        "created_at",
        "updated_at",
    ],
    "file_references": [
        "id",
        "session_id",
        "message_id",
        "file_path",
        "tool_name",
        "timestamp",
    ],
    "study_progress": [
        "id",
        "topic",
        "concept",
        "confidence",
        "first_seen",
        "last_seen",
        "session_count",
        "notes",
        "created_at",
        "updated_at",
        "last_teachback_score",
        "angles_used",
        "mastery_signals",
        "concept_id",
    ],
    "study_sessions": [
        "id",
        "session_id",
        "topic",
        "energy_level",
        "started_at",
        "ended_at",
        "duration_minutes",
        "pomodoro_cycles",
        "notes",
        "created_at",
        "persona_hash",
        "win_count",
        "struggle_count",
        "topic_slug",
        "updated_at",
    ],
    # R-19e: no "id" -- INTEGER PRIMARY KEY AUTOINCREMENT is a per-machine
    # counter, not a cross-machine identity (arbitration A5). "sync_key" is
    # the stable, migration-backfilled conflict target instead.
    "teach_back_scores": [
        "sync_key",
        "concept",
        "topic",
        "session_id",
        "score_accuracy",
        "score_own_words",
        "score_structure",
        "score_depth",
        "score_transfer",
        "review_type",
        "question_angle",
        "notes",
        "created_at",
        "updated_at",
    ],
    # R-19e: see teach_back_scores' comment above -- same reasoning.
    "knowledge_bridges": [
        "sync_key",
        "source_concept",
        "source_domain",
        "target_concept",
        "target_domain",
        "structural_mapping",
        "quality",
        "times_used",
        "times_helpful",
        "created_by",
        "created_at",
        "updated_at",
    ],
    "concepts": ["id", "name", "domain", "description", "created_at", "updated_at"],
    "concept_aliases": ["alias", "concept_id", "updated_at"],
    # R-19e: no "id" either -- but concept_relations already has a real
    # natural key (UNIQUE(source_concept_id, target_concept_id,
    # relation_type), migrations.py migrate_v12), so no sync_key column is
    # needed here; the fix is just using that constraint as the conflict
    # target (GLOBAL_TABLE_PRIMARY_KEYS below) instead of the autoincrement id.
    "concept_relations": [
        "source_concept_id",
        "target_concept_id",
        "relation_type",
        "confidence",
        "evidence_session_id",
        "evidence_message_id",
        "created_by",
        "created_at",
        "updated_at",
    ],
    "message_concepts": ["message_id", "concept_id", "confidence", "updated_at"],
    # R-19e: see teach_back_scores' comment above -- same reasoning.
    "parked_topics": [
        "sync_key",
        "study_session_id",
        "session_id",
        "topic_tag",
        "question",
        "context",
        "status",
        "scheduled_for",
        "resolved_at",
        "parked_at",
        "created_by",
        "source",
        "tech_area",
        "priority",
        "updated_at",
    ],
    # R-19e: see teach_back_scores' comment above -- same reasoning.
    "scrub_log": [
        "sync_key",
        "session_id",
        "message_id",
        "entity_type",
        "placeholder",
        "scrubbed_at",
        "updated_at",
    ],
}

# Primary/conflict key columns per GLOBAL_SYNC_TABLES row, used to build the
# recency-gated upsert in `_build_global_upsert_select_sql` (R-19 / D1). These
# match each table's `CREATE TABLE` in migrations.py exactly -- SQLite's
# `ON CONFLICT(...)` target must name a unique index or the table's own
# PRIMARY KEY/UNIQUE constraint.
GLOBAL_TABLE_PRIMARY_KEYS: dict[str, list[str]] = {
    "study_progress": ["id"],
    "study_sessions": ["id"],
    # R-19e (arbitration A5): these four were "id" (INTEGER PRIMARY KEY
    # AUTOINCREMENT, a per-machine counter, not a cross-machine identity --
    # two machines' row #1s collide silently). Now a migration-backfilled,
    # trigger-maintained sync_key column (migrations.py migrate_v30).
    "teach_back_scores": ["sync_key"],
    "knowledge_bridges": ["sync_key"],
    "concepts": ["id"],
    "concept_aliases": ["alias", "concept_id"],
    # R-19e: also "id" before -- concept_relations already had a real
    # natural key (UNIQUE(source_concept_id, target_concept_id,
    # relation_type), migrate_v12), so it needs no new column, just this
    # conflict-target change.
    "concept_relations": ["source_concept_id", "target_concept_id", "relation_type"],
    "message_concepts": ["message_id", "concept_id"],
    "parked_topics": ["sync_key"],
    "scrub_log": ["sync_key"],
}

# Module-level logger — does NOT configure the root logger (no basicConfig here).
# Logging is set up in the app callback below, which only runs when this module
# is used as a CLI tool.  Library callers (tests, MCP server, etc.) are
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


# Create Typer app
app = typer.Typer(
    name="session-sync",
    help="Sync sessions.db between machines.",
    add_completion=True,
    rich_markup_mode="rich",
)

console = Console()


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


# Session ID validation — prevent SQL injection via crafted IDs from remote DBs
_SAFE_SESSION_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_session_ids(session_ids: set[str]) -> set[str]:
    """Validate session IDs contain only safe characters."""
    for sid in session_ids:
        if not _SAFE_SESSION_ID.match(sid):
            raise ValueError(f"Invalid session ID (unsafe characters): {sid!r}")
    return session_ids


# SSH multiplexing options — reuse connections to avoid port exhaustion
# Use user-private directory instead of /tmp to prevent TOCTOU attacks
_SSH_MUX_DIR = (
    Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache")))
    / "session-sync-ssh"
)
_SSH_MUX_OPTS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=2",
    "-o",
    "ControlMaster=auto",
    "-o",
    f"ControlPath={_SSH_MUX_DIR}/%r@%h:%p",
    "-o",
    "ControlPersist=30",
]


def _ensure_mux_dir() -> None:
    _SSH_MUX_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def _resolve_remote(remote: str, tier: str = "hot") -> tuple[str, str]:
    """Resolve a remote target to (user@host, db_path).

    Accepts either:
    - An endpoint name from config (e.g. "macmini")
    - A full remote path (e.g. "user@host:/path/to/db")

    ``tier`` selects which remote DB an endpoint entry points at: "hot"
    uses ``sessions_db``, "full" uses ``full_db``. Explicit user@host:path
    remotes ignore tier (the path is already explicit).
    """
    # Check if it's a configured endpoint name
    endpoints = get_endpoints(_get_config())
    if remote in endpoints:
        ep = endpoints[remote]
        username = ep["username"]
        if tier == "full":
            path = ep.get("full_path", "")
            if not path:
                raise typer.BadParameter(
                    f"Endpoint '{remote}' has no 'full_db' configured — add it "
                    "to the host entry in config.yaml to sync the full tier."
                )
        else:
            path = ep["path"]
        _ensure_mux_dir()
        # Try primary IP, fall back to secondary
        for ip_key in ("primary_ip", "secondary_ip"):
            ip = ep.get("ip_address", {}).get(ip_key)
            if not ip:
                continue
            host = f"{username}@{ip}"
            try:
                subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=3", *_SSH_MUX_OPTS, host, "true"],
                    capture_output=True,
                    timeout=5,
                )
                console.print(
                    f"[dim]Resolved endpoint '{remote}' ({tier}) → {host}:{path}[/dim]"
                )
                return host, path
            except (subprocess.TimeoutExpired, OSError):
                console.print(f"[dim]{ip_key} ({ip}) unreachable, trying next...[/dim]")
                continue
        raise typer.BadParameter(f"Endpoint '{remote}': all IPs unreachable")

    # Fall back to user@host:/path format
    if ":" not in remote:
        raise typer.BadParameter(
            f"'{remote}' is not a configured endpoint or valid remote (user@host:/path)"
        )
    host, db_path = remote.split(":", 1)
    return host, db_path


def _local_db_for_tier(tier: str, db_override: Path | None) -> Path:
    """Resolve the local DB for a tier ('hot' -> sessions.db, 'full' -> record)."""
    if db_override:
        return db_override
    if tier == "full":
        from agent_session_tools.tiering import get_full_db_path

        full = get_full_db_path(_get_config())
        if full is None:
            raise typer.BadParameter(
                "database.full_db_path is not configured — cannot sync the "
                "full tier on this machine."
            )
        return full
    return _get_db_path()


def _pruned_session_ids(exclude_ids: set[str]) -> set[str]:
    """Of ``exclude_ids``, return those present in the local full DB.

    Used by hot-tier pulls: a session the remote has but the local hot DB
    lacks is NOT new if the local full DB holds it — it was pruned locally
    and must not be resurrected. Returns an empty set when tiering is
    disabled or the full DB is unreachable (pull then behaves as before).
    """
    if not exclude_ids:
        return set()
    try:
        from agent_session_tools.tiering import get_full_db_path

        full = get_full_db_path(_get_config())
        if full is None or not full.exists():
            return set()
        conn = sqlite3.connect(f"file:{full}?mode=ro", uri=True)
        try:
            known = {r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()}
        finally:
            conn.close()
        return exclude_ids & known
    except sqlite3.Error:
        return set()


def _quote_remote_path(path: str) -> str:
    """Quote a path for remote shell execution, expanding ~/."""
    if path.startswith("~/"):
        return f'"$HOME/{path[2:]}"'
    return shlex.quote(path)


def _remote_db_exists(host: str, db_path: str) -> bool:
    """Check if a usable database exists on the remote host.

    Verifies both that the file exists AND contains the sessions table.
    An empty file or wrong-schema DB returns False.
    """
    _ensure_mux_dir()
    remote_path = _quote_remote_path(db_path)
    # Check file exists AND has the sessions table
    result = subprocess.run(
        [
            "ssh",
            *_SSH_MUX_OPTS,
            host,
            f"test -f {remote_path} && sqlite3 {remote_path} "
            f"{shlex.quote('SELECT COUNT(*) FROM sessions LIMIT 1')}",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _sanitize_ontology_snapshot(snapshot_path: Path) -> None:
    """Strip every row of the six v48 ontology tables from a seed snapshot.

    The tier-1 ontology is derived, never synced (design: "Seed
    sanitization", Q1(a)) -- ``SYNC_TABLES`` and ``GLOBAL_SYNC_TABLES``
    never list any ``ontology_*`` table, and this whole-file seed is the one
    code path that still moves an entire database snapshot between
    machines. This leaves the ontology schema intact (so the snapshot opens
    without error) but with zero rows: the destination is expected to
    rebuild its own ontology -- the same incremental/full rebuild B2 wires
    into ``export_sessions._run_export``, or an explicit ``session-maint
    ontology-rebuild`` -- before it is considered ready.

    Deleting ``ontology_build_state`` in particular *is* the marker that
    makes that rebuild happen: with no recorded build state,
    ``ontology.rebuild_ontology(..., incremental=True)`` unconditionally
    falls back to a full rebuild (see ``ontology._read_build_state``)
    rather than silently trusting a seeded-then-stripped state as current.
    """
    from .ontology import ONTOLOGY_TABLES

    conn = sqlite3.connect(snapshot_path)
    try:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table in sorted(ONTOLOGY_TABLES & present):
            conn.execute(f'DELETE FROM "{table}"')
        conn.commit()
    finally:
        conn.close()


def _seed_remote_db(host: str, remote_db: str, local_db: Path) -> bool:
    """Copy local DB to remote for first-time sync. Creates remote directory."""
    legacy_guard.check_path(local_db, whole_file=True)
    _ensure_mux_dir()
    remote_dir = _quote_remote_path(str(Path(remote_db).parent))
    # Ensure remote directory exists
    subprocess.run(
        ["ssh", *_SSH_MUX_OPTS, host, f"mkdir -p {remote_dir}"],
        capture_output=True,
    )
    # SQLite online backup includes committed WAL pages without copying a live DB.
    with tempfile.TemporaryDirectory(prefix="session-sync-seed-") as tmp:
        snapshot = Path(tmp) / "sessions.db"
        with sqlite3.connect(local_db) as source, sqlite3.connect(snapshot) as dest:
            source.backup(dest)
            legacy_guard.check_database(dest)
        # Never seed a remote with a source's derived ontology -- the
        # remote's tier-1 ontology must be derived on the remote itself.
        _sanitize_ontology_snapshot(snapshot)
        legacy_guard.check_path(local_db, whole_file=True)
        result = subprocess.run(
            [
                "scp",
                *_SSH_MUX_OPTS,
                str(snapshot),
                f"{host}:{remote_db}",
            ],
            capture_output=True,
            text=True,
        )
    return result.returncode == 0


def _remote_sql(host: str, db_path: str, query: str) -> str:
    """Execute a SQL query on the remote DB via SSH and return stdout."""
    _ensure_mux_dir()
    remote_path = _quote_remote_path(db_path)
    result = subprocess.run(
        [
            "ssh",
            *_SSH_MUX_OPTS,
            host,
            f"sqlite3 {remote_path} {shlex.quote(query)}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Remote SQL failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _get_session_ids(
    db_path_or_host: Path | str, remote_db: str | None = None
) -> set[str]:
    """Get all session IDs from a local or remote DB."""
    if isinstance(db_path_or_host, Path):
        conn = sqlite3.connect(db_path_or_host)
        ids = {r[0] for r in conn.execute("SELECT id FROM sessions").fetchall()}
        conn.close()
        return ids
    # Remote
    assert remote_db is not None, "remote_db required for remote queries"
    raw = _remote_sql(db_path_or_host, remote_db, "SELECT id FROM sessions")
    return set(raw.splitlines()) if raw else set()


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _require_current_schema(target: Path | tuple[str, str]) -> None:
    """Reject incompatible databases before building or streaming a large dump.

    Native repair applies migrations behind its backup; sync never guesses
    missing columns or discards populated source fields to fit an old schema.
    """
    from agent_session_tools.migrations import CURRENT_VERSION

    if isinstance(target, Path):
        with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        location = "local machine"
        path = str(target)
    else:
        host, path = target
        raw = _remote_sql(host, path, "PRAGMA user_version")
        try:
            version = int(raw)
        except ValueError as exc:
            raise RuntimeError(
                "Cannot read remote database schema version; no sync attempted"
            ) from exc
        location = f"remote machine {host}"
    if version < CURRENT_VERSION:
        raise RuntimeError(
            f"Database schema v{version} on {location} is older than required v{CURRENT_VERSION}. "
            f"Run session-repair --apply --db {shlex.quote(path)} on that machine, then retry session-sync all. "
            "No conversation data has been transferred."
        )
    if version > CURRENT_VERSION:
        raise RuntimeError(
            f"Database schema v{version} on {location} is newer than this tool's v{CURRENT_VERSION}; "
            "upgrade agent-session-tools on both machines before syncing."
        )
    if not isinstance(target, Path):
        _check_legacy_remote(*target)


def _check_legacy_remote(host: str, db_path: str) -> set[str]:
    tables = set(
        _remote_sql(
            host, db_path, "SELECT name FROM sqlite_master WHERE type='table'"
        ).splitlines()
    )
    queries = list(legacy_guard.protected_queries(tables))
    if queries:
        query = (
            "SELECT CASE WHEN "
            + " OR ".join("EXISTS(" + q + ")" for q in queries)
            + " THEN 1 ELSE 0 END"
        )
        if _remote_sql(host, db_path, query) != "0":
            raise legacy_guard.LegacySyncRefused(legacy_guard.MESSAGE)
    return tables


def _build_insert_select_sql(
    table: str,
    *,
    id_filter: str | None = None,
    include_seq: bool = False,
) -> str:
    """Emit additive UPSERTs; never REPLACE rows carrying local evidence."""
    columns = list(TABLE_SYNC_COLUMNS[table])
    if table == "messages" and include_seq:
        columns.append("seq")
    quoted_columns = [_quote_identifier(column) for column in columns]
    literal_expr = " || ',' || ".join(f"quote({col})" for col in quoted_columns)
    where_clause = f" WHERE {id_filter}" if id_filter else ""
    if table == "sync_session_revisions":
        suffix = (
            " ON CONFLICT(session_id,machine_id) DO UPDATE SET seq=excluded.seq "
            "WHERE excluded.seq > sync_session_revisions.seq;"
        )
    elif table in {"sessions", "messages"}:
        # Only fill absent fields. A different nonempty message is a conflict,
        # not a newer version merely because its session timestamp increased.
        assignments = []
        for col in columns:
            if col in {"id", "source", "session_id"}:
                continue
            value = f"COALESCE(NULLIF({table}.{col}, ''), excluded.{col})"
            if table == "messages" and col == "role":
                value = "CASE WHEN COALESCE(messages.content, '') = '' THEN excluded.role ELSE messages.role END"
            if table == "sessions" and col == "updated_at":
                value = "CASE WHEN julianday(excluded.updated_at) > COALESCE(julianday(sessions.updated_at), 0) THEN excluded.updated_at ELSE COALESCE(sessions.updated_at, excluded.updated_at) END"
            assignments.append(f"{col} = {value}")
        suffix = " ON CONFLICT(id) DO UPDATE SET " + ", ".join(assignments) + ";"
    else:
        # Preserve destination annotations and union new tags/references.
        suffix = " ON CONFLICT DO NOTHING;"
    if table == "messages":
        # Do not resurrect empty exporter artifacts absent at the destination.
        # Existing empty IDs remain available to their evidence references.
        # A source-only reference to an omitted row fails the transaction under
        # foreign_keys=ON, requiring explicit repair instead of silently loss.
        def literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        prefix = f"INSERT INTO messages ({', '.join(quoted_columns)}) SELECT "
        condition = " WHERE trim(coalesce("
        between = ", '')) != '' OR EXISTS(SELECT 1 FROM messages WHERE id="
        return (
            f"SELECT {literal(prefix)} || {literal_expr} || {literal(condition)} "
            f"|| quote(content) || {literal(between)} || quote(id) "
            f"|| {literal(')' + suffix)} FROM messages{where_clause};"
        )
    suffix_literal = suffix.replace("'", "''")
    return (
        f"SELECT 'INSERT INTO {table} ({', '.join(quoted_columns)}) VALUES (' "
        f"|| {literal_expr} || '){suffix_literal}' FROM {table}{where_clause};"
    )


def _build_global_upsert_select_sql(table: str) -> str:
    """Build a SELECT emitting a recency-gated upsert for one global-sync table.

    Every row of a ``GLOBAL_SYNC_TABLES`` table is dumped with no per-row
    filter. Session-scoped rows use a separate conservative merge policy;
    global learning state instead retains its existing recency policy. Without a recency check, a stale machine's
    dump silently reverts a newer row the destination already has (a board
    move, a teach-back score, a progress update).

    So the gate has to travel with the row instead of living in a Python-side
    filter: emit ``INSERT ... ON CONFLICT(<pk>) DO UPDATE SET ... WHERE
    excluded.updated_at > COALESCE(<table>.updated_at, '')``. SQLite evaluates
    that WHERE clause on the destination, at apply time, against the
    destination's own current row -- so this is correct whether the
    generated SQL is streamed into a local file or piped into a remote
    ``sqlite3`` over SSH; no round-trip to read the destination first is
    needed. If the destination row is newer (or equal), the ON CONFLICT
    branch's WHERE is false, so SQLite neither inserts (conflict) nor
    updates (WHERE unmet) -- the destination row survives untouched.

    R-19b (M3 council, arbitration A1/A1'): a bare ``excluded.updated_at >
    <table>.updated_at`` is NULL-falsy -- SQL comparisons involving NULL
    evaluate to NULL, and a NULL WHERE result is treated as false. A
    destination row whose ``updated_at`` is NULL therefore could never be
    overwritten by *any* source row, however new, freezing it forever. The
    ``COALESCE(<table>.updated_at, <very old date>)`` on the destination side
    treats a NULL destination as "older than any real timestamp", so a dated
    source row now correctly wins. The source side is deliberately left
    bare: a NULL *source* `updated_at` (``excluded.updated_at > ...``) still
    evaluates to NULL/false and is skipped -- "no signal" from the incoming
    row should never win, only a destination with no signal should lose.
    Both halves of this decision are covered by `test_sync_r19.py`.

    R-19f (M3 council, arbitration X1): both sides are wrapped in SQLite's
    ``datetime()`` rather than compared as bare strings. Every current
    writer of a ``GLOBAL_SYNC_TABLES`` ``updated_at`` uses SQL
    ``datetime('now')``/``CURRENT_TIMESTAMP`` (both produce the same
    canonical ``YYYY-MM-DD HH:MM:SS`` form -- confirmed table-by-table in
    `evidence/M3/R-19f/00-dod.md`), so today's writes never actually hit a
    mismatch here. But real format heterogeneity for timestamps genuinely
    exists elsewhere in this codebase (the `sessions.updated_at` exporters:
    kiro/codex's UTC-aware ``isoformat()``, Claude's raw ``...Z`` passthrough,
    opencode's naive ``isoformat()``), and a bare string compare is silently
    wrong across formats that put a different character at the same
    position -- e.g. ``'...T00:00:01Z' > '...23:59:59'`` is true by pure
    lexical accident (``'T' > ' '`` in ASCII), even though 00:00:01 is hours
    *earlier* the same day. `datetime()` normalizes any SQLite-recognised
    time-string (space- or T-separated, Z-suffixed, +HH:MM-offset, with or
    without fractional seconds) to the same canonical form before comparing,
    so this gate is not silently wrong if a future writer -- or a foreign
    row synced in from an older/different format -- ever disagrees with
    today's uniform writers. ``datetime()`` of an empty string or NULL
    returns NULL, so the destination fallback uses ``'0001-01-01'`` (a real
    parseable "infinitely old" date), not ``''`` -- an empty-string fallback
    wrapped in ``datetime()`` would silently turn back into NULL and
    reopen the R-19b bug it's meant to prevent.
    """
    columns = TABLE_SYNC_COLUMNS[table]
    pk_columns = GLOBAL_TABLE_PRIMARY_KEYS[table]
    quoted_columns = [_quote_identifier(column) for column in columns]
    concept_columns = {
        "concepts": {"id"},
        "concept_aliases": {"concept_id"},
        "concept_relations": {"source_concept_id", "target_concept_id"},
        "message_concepts": {"concept_id"},
    }.get(table, set())

    def emitted_value(column: str) -> str:
        quoted = _quote_identifier(column)
        if column in concept_columns:
            return (
                "'(SELECT target_id FROM sync_concept_ids WHERE source_id=' || quote("
                + quoted
                + ") || ')'"
            )
        return f"quote({quoted})"

    literal_expr = " || ',' || ".join(emitted_value(column) for column in columns)
    update_columns = [c for c in columns if c not in pk_columns]
    set_clause = ", ".join(
        f"{_quote_identifier(c)} = excluded.{_quote_identifier(c)}"
        for c in update_columns
    )
    conflict_target = ", ".join(_quote_identifier(c) for c in pk_columns)
    updated_at_col = _quote_identifier("updated_at")
    # parked_topics has the sync UUID plus known natural uniqueness: modern
    # pending(question,source), or the legacy session/question/source tuple.
    # Catch that table's alternative constraints without changing its schema;
    # preserve destination id/sync_key and apply the same recency policy.
    conflict_clause = (
        "ON CONFLICT" if table == "parked_topics" else f"ON CONFLICT({conflict_target})"
    )
    return (
        f"SELECT 'INSERT INTO {table} "
        f"({', '.join(quoted_columns)}) VALUES (' || {literal_expr} || ') "
        f"{conflict_clause} DO UPDATE SET {set_clause} "
        f"WHERE datetime(excluded.{updated_at_col}) > "
        f"datetime(COALESCE({table}.{updated_at_col}, ''0001-01-01''));' "
        f"FROM {table};"
    )


def _build_concept_map_select_sql() -> str:
    """Emit transient source-ID mappings before inserting concepts/edges.

    A natural name/domain match keeps the destination concept ID, ensuring
    pre-existing references remain valid; incoming references use the map.
    """
    return """
    SELECT 'INSERT INTO sync_concept_ids(source_id,target_id,name,domain) VALUES ('
      || quote(id) || ', COALESCE((SELECT id FROM concepts WHERE name='
      || quote(name) || ' AND domain=' || quote(domain) || '), '
      || quote(id) || '), ' || quote(name) || ', ' || quote(domain) || ');'
    FROM concepts;
    """


def _parked_json_expression(columns: list[str]) -> str:
    pairs = []
    for column in sorted(columns):
        pairs.extend(["'" + column.replace("'", "''") + "'", _quote_identifier(column)])
    return "json_object(" + ", ".join(pairs) + ")"


def _build_parked_archive_select_sql(columns: list[str]) -> str:
    """Emit complete original source rows, including host-specific columns."""
    prefix = "INSERT OR IGNORE INTO sync_row_archive(table_name,row_json) VALUES ('parked_topics',"
    escaped = prefix.replace("'", "''")
    return f"SELECT '{escaped}' || quote({_parked_json_expression(columns)}) || ');' FROM parked_topics;"


def _remote_dump_queries(host: str, db_path: str, session_ids: set[str]) -> list[str]:
    tables = _check_legacy_remote(host, db_path)
    message_columns = set(
        _remote_sql(
            host, db_path, "SELECT name FROM pragma_table_info('messages')"
        ).splitlines()
    )
    parked_columns = (
        _remote_sql(
            host, db_path, "SELECT name FROM pragma_table_info('parked_topics')"
        ).splitlines()
        if "parked_topics" in tables
        else []
    )
    return [
        legacy_guard.transaction_guard(tables),
        *_build_dump_queries(
            session_ids,
            tables,
            include_seq="seq" in message_columns,
            parked_columns=parked_columns,
        ),
    ]


def _build_dump_queries(
    session_ids: set[str],
    available_tables: set[str] | None = None,
    *,
    include_seq: bool = False,
    parked_columns: list[str] | None = None,
) -> list[str]:
    """Build SQL queries that emit replayable INSERT statements."""

    def _has_table(table: str) -> bool:
        return available_tables is None or table in available_tables

    queries: list[str] = []
    if parked_columns and _has_table("parked_topics"):
        queries.append(_build_parked_archive_select_sql(parked_columns))
    if available_tables is not None and "sync_row_archive" in available_tables:
        queries.append(
            "SELECT 'INSERT OR IGNORE INTO sync_row_archive(table_name,row_json) VALUES (' || quote(table_name) || ',' || quote(row_json) || ');' FROM sync_row_archive;"
        )
    if session_ids:
        placeholders = ",".join(f"'{sid}'" for sid in session_ids)
        if _has_table("sessions"):
            queries.append(
                _build_insert_select_sql(
                    "sessions", id_filter=f"id IN ({placeholders})"
                )
            )
        for table in SYNC_TABLES:
            if table == "sessions" or not _has_table(table):
                continue
            queries.append(
                _build_insert_select_sql(
                    table,
                    id_filter=f"session_id IN ({placeholders})",
                    include_seq=include_seq,
                )
            )

    for table in GLOBAL_SYNC_TABLES:
        if not _has_table(table):
            continue
        if table == "concepts":
            queries.append(_build_concept_map_select_sql())
        queries.append(_build_global_upsert_select_sql(table))
    return queries


def _timestamp_key(value: str | None) -> tuple[int, object]:
    """Return a comparable key for sync timestamps across mixed formats."""
    if value is None:
        return (0, "")

    text = str(value).strip()
    if not text:
        return (0, "")

    if text.isdigit():
        raw = int(text)
        # Treat 13+ digit values as milliseconds since epoch
        if raw >= 10**12:
            raw = raw / 1000
        try:
            return (2, datetime.fromtimestamp(raw, tz=UTC))
        except (OverflowError, OSError, ValueError):
            return (1, text)

    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return (1, text)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return (2, dt)


_SessionSyncState = tuple[str, dict[str, int], frozenset[str]]


def _local_session_states(db_path: Path) -> dict[str, _SessionSyncState]:
    """Read timestamp, replica vector, and captured message identities."""
    with sqlite3.connect(db_path) as conn:
        sessions = {
            row[0]: [row[1] or "", {}, set()]
            for row in conn.execute("SELECT id,updated_at FROM sessions")
        }
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "sync_session_revisions" in tables:
            for session_id, machine_id, seq in conn.execute(
                "SELECT session_id,machine_id,seq FROM sync_session_revisions"
            ):
                if session_id in sessions:
                    sessions[session_id][1][machine_id] = seq
        for session_id, message_id in conn.execute(
            "SELECT session_id,id FROM messages"
        ):
            if session_id in sessions:
                sessions[session_id][2].add(message_id)
    return {
        session_id: (state[0], dict(state[1]), frozenset(state[2]))
        for session_id, state in sessions.items()
    }


def _remote_session_states(host: str, db_path: str) -> dict[str, _SessionSyncState]:
    """Read the same bounded state from a peer in one remote query."""
    query = """SELECT json_object(
      'id',s.id,
      'updated_at',coalesce(s.updated_at,''),
      'versions',json(coalesce((SELECT json_group_object(machine_id,seq)
        FROM sync_session_revisions r WHERE r.session_id=s.id),'{}')),
      'messages',json(coalesce((SELECT json_group_array(id) FROM
        (SELECT id FROM messages m WHERE m.session_id=s.id ORDER BY id)),'[]'))
    ) FROM sessions s ORDER BY s.id"""
    states: dict[str, _SessionSyncState] = {}
    for line in _remote_sql(host, db_path, query).splitlines():
        if not line:
            continue
        if not line.startswith("{"):
            session_id, _, updated_at = line.partition("|")
            states[session_id] = (updated_at, {}, frozenset())
            continue
        row = json.loads(line)
        states[row["id"]] = (
            row["updated_at"],
            {str(key): int(value) for key, value in row["versions"].items()},
            frozenset(str(value) for value in row["messages"]),
        )
    return states


def _source_has_changes(
    source: _SessionSyncState, destination: _SessionSyncState
) -> bool:
    """Return whether one replica owns content/version state the other lacks."""
    source_time, source_versions, source_messages = source
    destination_time, destination_versions, destination_messages = destination
    if not destination_versions and not destination_messages:
        # Compatibility with pre-v50/mocked timestamp-only state responses.
        return _timestamp_key(source_time) > _timestamp_key(destination_time)
    if source_messages - destination_messages:
        return True
    if any(
        seq > destination_versions.get(machine_id, -1)
        for machine_id, seq in source_versions.items()
    ):
        return True
    return _timestamp_key(source_time) > _timestamp_key(destination_time)


def _get_sync_state(
    local_db: Path, host: str, remote_db: str, reconcile: bool = False
) -> tuple[set[str], set[str]]:
    """Select sessions with source-owned replica versions or message IDs."""
    local_sessions = _local_session_states(local_db)
    remote_sessions = _remote_session_states(host, remote_db)
    new_ids = set(local_sessions) - set(remote_sessions)
    updated_ids = {
        session_id
        for session_id in set(local_sessions) & set(remote_sessions)
        if reconcile
        or _source_has_changes(local_sessions[session_id], remote_sessions[session_id])
    }
    return new_ids, updated_ids


def _dump_delta_sql(db_path: Path, session_ids: set[str]) -> str:
    """Generate additive replayable SQL from a consistent source read snapshot.

    Includes the selected conversations, global learning metadata, and durable
    parked-topic snapshots; all values are quoted by SQLite itself.
    """
    if not session_ids:
        return ""

    legacy_guard.check_config(load_config())
    _validate_session_ids(session_ids)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")
        legacy_guard.check_database(conn)
        available_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        lines: list[str] = []
        include_seq = any(
            row[1] == "seq" for row in conn.execute("PRAGMA table_info(messages)")
        )
        parked_columns = [
            row[1] for row in conn.execute("PRAGMA table_info(parked_topics)")
        ]
        for query in _build_dump_queries(
            session_ids,
            available_tables,
            include_seq=include_seq,
            parked_columns=parked_columns,
        ):
            lines.extend(row[0] for row in conn.execute(query).fetchall())
        legacy_guard.check_path(db_path)
        return "\n".join(lines) + ("\n" if lines else "")
    finally:
        conn.close()


# FTS repair appended to every import. Two reasons this must rebuild from
# the messages table rather than use FTS5's ('rebuild') command:
# 1. Legacy INSERT OR REPLACE statements fired insert triggers but NOT
#    delete triggers (SQLite's REPLACE skips them unless recursive_triggers
#    is on), so every updated session leaks orphaned FTS rows.
# 2. ('rebuild') rebuilds the inverted index from the FTS table's OWN
#    content store — it preserves those orphans. This exact mechanism once
#    grew a sessions DB to 45GB.
_FTS_REPAIR_SQL = (
    "DELETE FROM messages_fts;\n"
    "INSERT INTO messages_fts(rowid, content, session_id, role) "
    "SELECT rowid, content, session_id, role FROM messages "
    "WHERE content IS NOT NULL;\n"
)


_SYNC_TRANSACTION_PREFIX = """
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS sync_row_archive(table_name TEXT NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY(table_name,row_json)) WITHOUT ROWID;
CREATE TEMP TABLE sync_archive_before(n INTEGER);
INSERT INTO sync_archive_before SELECT count(*) FROM sync_row_archive;
CREATE TEMP TABLE sync_run_conflicts(message_id TEXT PRIMARY KEY);
CREATE TEMP TABLE sync_concept_ids(source_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, name TEXT, domain TEXT);
CREATE TEMP TRIGGER sync_concept_identity BEFORE INSERT ON sync_concept_ids
WHEN EXISTS(SELECT 1 FROM concepts WHERE id=NEW.target_id AND (name IS NOT NEW.name OR domain IS NOT NEW.domain))
BEGIN SELECT RAISE(ABORT, 'Concept identity conflict'); END;

CREATE TEMP TRIGGER sync_message_identity BEFORE INSERT ON main.messages
WHEN EXISTS(SELECT 1 FROM messages WHERE id=NEW.id AND session_id != NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'Message identity conflict'); END;
CREATE TEMP TRIGGER sync_session_identity BEFORE INSERT ON main.sessions
WHEN EXISTS(SELECT 1 FROM sessions WHERE id=NEW.id AND source != NEW.source)
BEGIN SELECT RAISE(ABORT, 'Session identity conflict'); END;
CREATE TEMP TRIGGER sync_content_conflict BEFORE INSERT ON main.messages
WHEN EXISTS(SELECT 1 FROM messages WHERE id=NEW.id AND COALESCE(content,'') != ''
 AND COALESCE(NEW.content,'') != '' AND content != NEW.content)
BEGIN INSERT OR IGNORE INTO sync_run_conflicts VALUES(NEW.id); END;
"""


def _stream_sql_to_target(sql: str, target: Path | tuple[str, str]) -> bool:
    """Stream SQL into a local DB or remote DB over SSH.

    target is either a local Path or (host, db_path) tuple.
    """
    if not sql.strip():
        return True

    legacy_guard.check_config(load_config())
    if isinstance(target, Path):
        with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as conn:
            legacy_guard.check_database(conn)
            target_tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            parked_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(parked_topics)")
            ]
    else:
        target_tables = _check_legacy_remote(*target)
        parked_columns = _remote_sql(
            target[0], target[1], "SELECT name FROM pragma_table_info('parked_topics')"
        ).splitlines()
    archive_target = (
        (
            "INSERT OR IGNORE INTO sync_row_archive(table_name,row_json) SELECT 'parked_topics', "
            + _parked_json_expression(parked_columns)
            + " FROM parked_topics;\n"
        )
        if parked_columns
        else ""
    )
    persist_conflicts = (
        "INSERT OR IGNORE INTO main.sync_conflicts(message_id,first_detected_at) "
        "SELECT message_id,datetime('now') FROM sync_run_conflicts;\n"
        if "sync_conflicts" in target_tables
        else ""
    )
    sql = (
        _SYNC_TRANSACTION_PREFIX
        + legacy_guard.transaction_guard(target_tables)
        + archive_target
        + sql
        + "\n"
        + _FTS_REPAIR_SQL
        + archive_target
        + persist_conflicts
        + "SELECT 'sync_conflicts|' || count(*) FROM sync_run_conflicts;\n"
        "SELECT 'sync_archived|' || ((SELECT count(*) FROM sync_row_archive)-"
        "(SELECT n FROM sync_archive_before));\nCOMMIT;\n"
    )

    if isinstance(target, Path):
        result = subprocess.run(
            ["sqlite3", "-bail", str(target)],
            input=sql,
            capture_output=True,
            text=True,
        )
    else:
        host, db_path = target
        result = subprocess.run(
            [
                "ssh",
                *_SSH_MUX_OPTS,
                "-C",
                host,
                f"sqlite3 -bail {_quote_remote_path(db_path)}",
            ],
            input=sql,
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        logger.error(
            "SQL import failed; transaction rolled back: %s", result.stderr.strip()
        )
        return False
    for line in result.stdout.splitlines():
        if line.startswith("sync_archived|") and line.split("|", 1)[1] != "0":
            console.print(
                f"[dim]Preserved {line.split('|', 1)[1]} original metadata snapshots in sync_row_archive.[/dim]"
            )
        if line.startswith("sync_conflicts|") and line.split("|", 1)[1] != "0":
            console.print(
                f"[yellow]Retained destination content for {line.split('|', 1)[1]} divergent message(s); review with session-repair merge. No content was overwritten.[/yellow]"
            )
    return True


from agent_session_tools.maintenance import create_backup  # noqa: E402


# Remote backups older than the newest N per destination are rotated out on
# every call -- otherwise unbounded `.bak-<timestamp>` copies accumulate next
# to the remote DB forever (M3 council, arbitration A9). Mirrors
# `create_backup`'s local retention default (maintenance.py:database.backup_retention).
_REMOTE_BACKUP_RETENTION = 5


def _remote_backup(host: str, remote_db: str) -> str | None:
    """Back up the remote DB to a timestamped copy before writing to it.

    Mirrors `create_backup`'s naming (``<stem>.bak-<timestamp>`` next to the
    original) but runs the copy on the remote host over SSH, since the file
    is not locally reachable. R-19 / D1: `pull` already backs up the side
    that can lose data (`create_backup(local_db)`); `push` and the remote
    side of `sync` did not back up the *remote* -- the side their own writes
    can revert -- at all. Returns the remote backup path, or None if there is
    nothing to back up (remote DB absent) or the copy failed (logged, not
    raised here -- R-19d makes the *callers* decide whether a failed backup
    blocks the write; this function's only job is to attempt one and report
    whether it succeeded).

    R-19c (M3 council, arbitration A2): this used to be a plain `cp -p` of
    the remote file. In WAL mode, data committed but not yet checkpointed
    into the main `.db` file lives in the sibling `-wal` file -- a file copy
    of just the `.db` file silently misses it (verified directly: a row
    committed with no explicit checkpoint was present in a `.backup()` copy
    and absent from a `cp -p` of the same database at the same instant). The
    sqlite3 CLI's `.backup` dot-command is the same WAL-aware mechanism as
    Python's `sqlite3.Connection.backup()` (used by `maintenance.create_backup`
    for the equivalent local fix) -- it can run against the remote file over
    SSH without a live Python connection to it.
    """
    _ensure_mux_dir()
    remote_path = _quote_remote_path(remote_db)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{remote_db}.bak-{timestamp}"
    backup_sql = shlex.quote(f".backup '{backup_path}'")
    # Retention runs in the same SSH round-trip as the backup itself: list
    # this destination's own `.bak-*` copies newest-first, keep the newest
    # _REMOTE_BACKUP_RETENTION, delete the rest. The `while read` loop (not
    # `xargs`) is deliberate -- xargs's "don't run the command on empty
    # input" behaviour is a GNU extension (`-r`/`--no-run-if-empty`); BSD
    # xargs (macOS, most remote endpoints in practice) lacks the flag, and a
    # bare `xargs rm` on empty input still invokes `rm` with no arguments on
    # some platforms. A `while read` loop is a no-op on empty input on every
    # POSIX shell, with no flag to get wrong.
    rotate_cmd = (
        f"ls -t {remote_path}.bak-* 2>/dev/null | tail -n +{_REMOTE_BACKUP_RETENTION + 1} "
        '| while read -r f; do rm -f "$f"; done'
    )
    result = subprocess.run(
        [
            "ssh",
            *_SSH_MUX_OPTS,
            host,
            f"test -f {remote_path} && sqlite3 {remote_path} {backup_sql} && ({rotate_cmd})",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "Remote backup skipped for %s:%s (%s)",
            host,
            remote_db,
            result.stderr.strip() or "remote DB not found",
        )
        return None
    logger.info("Remote backup created: %s:%s", host, backup_path)
    return backup_path


def _backup_destination(target: Path | tuple[str, str]) -> Path | str | None:
    """Back up whatever `_stream_sql_to_target` is about to write to.

    R-19 / D1: `pull` has always backed up its destination
    (`create_backup(local_db)`, above in `pull()`) before applying a dump --
    it is the side that can lose data. `push` and the remote side of `sync`
    write to the *other* machine and took no backup at all. This dispatches
    to the same local `create_backup` `pull` uses when `target` is a local
    Path, or to `_remote_backup` when it is a (host, remote_db) tuple, so
    every write path backs up its destination the same way.
    """
    if isinstance(target, Path):
        if not target.exists():
            return None
        return create_backup(target)
    host, remote_db = target
    return _remote_backup(host, remote_db)


def show_db_stats(db_path: Path, label: str = "Database") -> None:
    """Show database statistics."""
    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    # Get sources breakdown
    sources = conn.execute(
        "SELECT source, COUNT(*) FROM sessions GROUP BY source ORDER BY COUNT(*) DESC"
    ).fetchall()

    conn.close()

    table = Table(title=f"{label}: {db_path.name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Sessions", str(sessions))
    table.add_row("Messages", str(messages))
    table.add_row("Size", f"{db_path.stat().st_size / 1024 / 1024:.1f} MB")

    for source, count in sources[:5]:
        table.add_row(f"  {source or 'unknown'}", str(count))

    console.print(table)


_tier_option = typer.Option(
    "--tier",
    help="Which DB tier to sync: 'hot' (local sessions.db, default) or "
    "'full' (complete-history record; endpoint needs 'full_db' configured).",
)


@app.command()
def pull(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[
        Path | None, typer.Option("--db", "-d", help="Local database path")
    ] = None,
    no_backup: Annotated[bool, typer.Option("--no-backup", help="Skip backup")] = False,
    tier: Annotated[str, _tier_option] = "hot",
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="Revisit shared sessions even when timestamps are unchanged",
        ),
    ] = False,
) -> None:
    """Pull new sessions from remote via SQL streaming."""
    if _structured(remote, db, tier, "pull"):
        return
    local_db = _local_db_for_tier(tier, db)
    legacy_guard.check_path(local_db)
    host, remote_db = _resolve_remote(remote, tier)

    console.print(f"[bold]Pulling from:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")
    console.print()

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    _require_current_schema(local_db)

    if not no_backup and create_backup(local_db) is None:
        console.print(
            "[red]Could not back up local destination; refusing to import without a backup.[/red]"
        )
        raise typer.Exit(1)

    show_db_stats(local_db, "Local (before)")

    if not _remote_db_exists(host, remote_db):
        console.print("[yellow]⚠ Remote database not found — nothing to pull.[/yellow]")
        console.print(
            f"[dim]Use 'session-sync push {remote}' to seed the remote first.[/dim]"
        )
        return

    _require_current_schema((host, remote_db))

    # Calculate delta: what does remote have that's new or newer?
    console.print("\n[bold]Calculating delta...[/bold]")
    # Reverse: remote is "local" from the perspective of what to pull
    # We need remote's updated_at vs our updated_at
    # Reuse _get_sync_state but swap: get remote sessions newer than ours
    remote_sessions = _remote_session_states(host, remote_db)
    local_sessions = _local_session_states(local_db)

    new_ids = set(remote_sessions) - set(local_sessions)
    if tier == "hot":
        # Prune-awareness: sessions we deliberately pruned live in the local
        # full DB — the remote having them does not make them "new".
        pruned = _pruned_session_ids(new_ids)
        if pruned:
            console.print(
                f"[dim]Skipping {len(pruned)} session(s) pruned locally "
                "(present in full DB).[/dim]"
            )
            new_ids -= pruned
    updated_ids = {
        sid
        for sid in set(remote_sessions) & set(local_sessions)
        if reconcile or _source_has_changes(remote_sessions[sid], local_sessions[sid])
    }
    all_ids = new_ids | updated_ids

    if not all_ids:
        console.print("[green]✅ Already up to date[/green]")
        return

    console.print(
        f"  New: [cyan]{len(new_ids)}[/cyan], Updated: [cyan]{len(updated_ids)}[/cyan]"
    )

    # Dump from remote
    _validate_session_ids(all_ids)
    commands = _remote_dump_queries(host, remote_db, all_ids)
    result = subprocess.run(
        [
            "ssh",
            *_SSH_MUX_OPTS,
            "-C",
            host,
            f"sqlite3 -bail {_quote_remote_path(remote_db)}",
        ],
        input="BEGIN;\n" + "\n".join(commands) + "\nCOMMIT;",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Remote dump failed; no data imported: "
            + (
                result.stderr.splitlines()[0]
                if result.stderr
                else f"exit {result.returncode}"
            )
        )
    sql = result.stdout

    console.print("[bold]Importing...[/bold]")
    if not _stream_sql_to_target(sql, local_db):
        console.print("[red]❌ Failed to import[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[green]✅ Pulled {len(new_ids)} new, {len(updated_ids)} updated[/green]"
    )
    show_db_stats(local_db, "Local (after)")


@app.command()
def push(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[
        Path | None, typer.Option("--db", "-d", help="Local database path")
    ] = None,
    tier: Annotated[str, _tier_option] = "hot",
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="Revisit shared sessions even when timestamps are unchanged",
        ),
    ] = False,
) -> None:
    """Push new and updated sessions to remote via SQL streaming."""
    if _structured(remote, db, tier, "push"):
        return
    local_db = _local_db_for_tier(tier, db)
    legacy_guard.check_path(local_db)
    host, remote_db = _resolve_remote(remote, tier)

    console.print(f"[bold]Pushing to:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    _require_current_schema(local_db)

    show_db_stats(local_db, "Local")

    # If remote DB doesn't exist, seed it with a full copy
    if not _remote_db_exists(host, remote_db):
        console.print(
            "\n[bold]Remote database not found — seeding with full copy...[/bold]"
        )
        if _seed_remote_db(host, remote_db, local_db):
            conn = sqlite3.connect(local_db)
            count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            conn.close()
            console.print(f"[green]✅ Seeded remote with {count} sessions[/green]")
        else:
            console.print("[red]❌ Failed to copy database to remote[/red]")
            raise typer.Exit(1)
        return

    _require_current_schema((host, remote_db))

    console.print("\n[bold]Calculating delta...[/bold]")
    new_ids, updated_ids = _get_sync_state(
        local_db, host, remote_db, reconcile=reconcile
    )
    all_ids = new_ids | updated_ids

    if not all_ids:
        console.print("[green]✅ Already up to date[/green]")
        return

    console.print(
        f"  New: [cyan]{len(new_ids)}[/cyan], Updated: [cyan]{len(updated_ids)}[/cyan]"
    )

    sql = _dump_delta_sql(local_db, all_ids)

    # Back up the remote before writing to it — R-19 / D1: `pull` has always
    # backed up its destination; `push` writes to the remote and, until now,
    # took no backup of the side it can revert.
    #
    # R-19d (M3 council, arbitration A3): a failed backup used to be silently
    # ignored (the return value was discarded) -- the write proceeded anyway.
    # The whole point of the backup is recoverability if the recency gate
    # somehow doesn't save the day, so a failed backup must abort the write,
    # not merely log a warning and continue.
    if _backup_destination((host, remote_db)) is None:
        console.print(
            f"[red]❌ Could not back up the remote destination "
            f"({host}:{remote_db}) — refusing to push without a backup[/red]"
        )
        raise typer.Exit(1)

    console.print("[bold]Streaming to remote...[/bold]")
    if _stream_sql_to_target(sql, (host, remote_db)):
        console.print(
            f"[green]✅ Pushed {len(new_ids)} new, {len(updated_ids)} updated[/green]"
        )
    else:
        console.print("[red]❌ Failed to push to remote[/red]")
        raise typer.Exit(1)


@app.command()
def sync(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[
        Path | None, typer.Option("--db", "-d", help="Local database path")
    ] = None,
    no_backup: Annotated[bool, typer.Option("--no-backup", help="Skip backup")] = False,
    tier: Annotated[str, _tier_option] = "hot",
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="Revisit shared sessions even when timestamps are unchanged",
        ),
    ] = False,
) -> None:
    """Two-way sync: stream deltas in both directions.

    Missing conversation data is exchanged; conflicting nonempty messages
    are retained on each destination and reported for review. In the hot tier, sessions
    pruned locally (present in the local full DB) are not pulled back.
    Use --tier full to consolidate the complete-history records.
    """
    if _structured(remote, db, tier, "sync"):
        return
    local_db = _local_db_for_tier(tier, db)
    legacy_guard.check_path(local_db)
    host, remote_db = _resolve_remote(remote, tier)

    console.print(f"[bold]Syncing with:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")
    console.print()

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    _require_current_schema(local_db)

    if not no_backup and create_backup(local_db) is None:
        console.print(
            "[red]Could not back up local destination; refusing to import without a backup.[/red]"
        )
        raise typer.Exit(1)

    _require_current_schema((host, remote_db))

    # Calculate deltas in both directions using one SSH call for remote state
    console.print("[bold]Calculating deltas...[/bold]")
    remote_sessions = _remote_session_states(host, remote_db)
    local_sessions = _local_session_states(local_db)

    # Push: local new + local newer
    push_new = set(local_sessions) - set(remote_sessions)
    push_updated = {
        sid
        for sid in set(local_sessions) & set(remote_sessions)
        if reconcile or _source_has_changes(local_sessions[sid], remote_sessions[sid])
    }
    # Pull: remote new + remote newer (hot tier: minus locally-pruned)
    pull_new = set(remote_sessions) - set(local_sessions)
    if tier == "hot":
        pruned = _pruned_session_ids(pull_new)
        if pruned:
            console.print(
                f"[dim]Skipping {len(pruned)} session(s) pruned locally "
                "(present in full DB).[/dim]"
            )
            pull_new -= pruned
    pull_updated = {
        sid
        for sid in set(local_sessions) & set(remote_sessions)
        if reconcile or _source_has_changes(remote_sessions[sid], local_sessions[sid])
    }

    console.print(
        f"  To pull: [cyan]{len(pull_new)}[/cyan] new, [cyan]{len(pull_updated)}[/cyan] updated"
    )
    console.print(
        f"  To push: [cyan]{len(push_new)}[/cyan] new, [cyan]{len(push_updated)}[/cyan] updated"
    )

    # Step 1: Pull remote → local
    pull_ids = pull_new | pull_updated
    if pull_ids:
        console.print(f"\n[bold]Step 1: Pulling {len(pull_ids)} sessions...[/bold]")
        _validate_session_ids(pull_ids)
        commands = _remote_dump_queries(host, remote_db, pull_ids)

        result = subprocess.run(
            [
                "ssh",
                *_SSH_MUX_OPTS,
                "-C",
                host,
                f"sqlite3 -bail {_quote_remote_path(remote_db)}",
            ],
            input="BEGIN;\n" + "\n".join(commands) + "\nCOMMIT;",
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Remote dump failed; no data imported: "
                + (
                    result.stderr.splitlines()[0]
                    if result.stderr
                    else f"exit {result.returncode}"
                )
            )
        sql = result.stdout
        if sql.strip() and not _stream_sql_to_target(sql, local_db):
            console.print("[red]❌ Failed to pull[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]✓ Pulled {len(pull_new)} new, {len(pull_updated)} updated[/green]"
        )
    else:
        console.print("\n[bold]Step 1:[/bold] Nothing to pull")

    # Step 2: Push local → remote
    push_ids = push_new | push_updated
    if push_ids:
        console.print(f"\n[bold]Step 2: Pushing {len(push_ids)} sessions...[/bold]")
        sql = _dump_delta_sql(local_db, push_ids)
        # Back up the remote before this step writes to it — R-19 / D1: the
        # local side is already backed up above (`create_backup(local_db)`,
        # gated on the same `no_backup` flag); the remote side of a two-way
        # sync gets the same protection pull has always given its own
        # destination.
        #
        # R-19d: a failed backup must abort this step's write, same as push.
        if (
            sql.strip()
            and not no_backup
            and _backup_destination((host, remote_db)) is None
        ):
            console.print(
                f"[red]❌ Could not back up the remote destination "
                f"({host}:{remote_db}) — refusing to push without a backup[/red]"
            )
            raise typer.Exit(1)
        if sql.strip() and not _stream_sql_to_target(sql, (host, remote_db)):
            console.print("[red]❌ Failed to push[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]✓ Pushed {len(push_new)} new, {len(push_updated)} updated[/green]"
        )
    else:
        console.print("\n[bold]Step 2:[/bold] Nothing to push")

    if not pull_ids and not push_ids:
        console.print("\n[green]✅ Already in sync[/green]")
    else:
        console.print("\n[green]✅ Sync complete![/green]")
    show_db_stats(local_db, "Final")


@app.command("all")
def sync_all(
    db: Annotated[
        Path | None, typer.Option("--db", "-d", help="Local database path")
    ] = None,
    tier: Annotated[str, _tier_option] = "hot",
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile/--incremental",
            help="Revisit unchanged sessions (default) or use timestamp deltas",
        ),
    ] = True,
) -> None:
    """Push to every configured peer first, then pull from every peer.

    Uses hosts (excluding this machine by hostname), or legacy endpoints.
    Failures are reported per operation; other peers are still attempted.
    """
    from .replication.coordinator import configured_peers

    structured = configured_peers()
    peers = structured if structured is not None else list(get_endpoints(_get_config()))
    if not peers:
        console.print(
            "[yellow]No remote sync targets configured. Add hosts to config.yaml.[/yellow]"
        )
        raise typer.Exit(1)
    failures = []
    for phase, operation in (("push", push), ("pull", pull)):
        for peer in peers:
            console.print(f"\n[bold]{phase.title()} {peer}[/bold]")
            try:
                operation(remote=peer, db=db, tier=tier, reconcile=reconcile)
            except Exception as exc:
                failures.append((phase, peer))
                console.print(
                    f"[red]{phase.title()} {peer} failed ({type(exc).__name__}): {exc}[/red]"
                )
    if failures:
        console.print(
            "[red]Failed operations: "
            + ", ".join(f"{phase} {peer}" for phase, peer in failures)
            + "[/red]"
        )
        raise typer.Exit(1)
    console.print(
        f"[green]Completed push then pull for {len(peers)} configured peer(s).[/green]"
    )


@app.command()
def status(
    db: Annotated[Path | None, typer.Option("--db", "-d", help="Database path")] = None,
) -> None:
    """Show local database status and sync info."""
    local_db = db or _get_db_path()

    if not local_db.exists():
        console.print(f"[red]❌ Database not found: {local_db}[/red]")
        raise typer.Exit(1)

    show_db_stats(local_db, "Local Database")

    # Show recent backups
    backup_dir = get_backup_dir(_get_config())
    if backup_dir.exists():
        backups = sorted(
            backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if backups:
            console.print(f"\n[bold]Recent backups:[/bold] ({backup_dir})")
            for backup in backups[:5]:
                mtime = datetime.fromtimestamp(backup.stat().st_mtime)
                size_mb = backup.stat().st_size / 1024 / 1024
                console.print(
                    f"  {backup.name} ({size_mb:.1f} MB) - {mtime:%Y-%m-%d %H:%M}"
                )


@app.command()
def endpoints() -> None:
    """List configured sync endpoints."""
    from .replication.coordinator import configured_peers

    peers = configured_peers()
    if peers is not None:
        cfg = load_config()
        table = Table(title="Configured memory peers")
        for label in ("Peer", "Host", "User", "Allowed scopes"):
            table.add_column(label)
        for peer in peers:
            item = cfg["memory"]["sync"]["peers"][peer]
            transport = item.get("ssh", {})
            table.add_row(
                peer,
                transport.get("host", "not configured"),
                transport.get("user", "not configured"),
                ", ".join(item.get("allowed_scopes", [])),
            )
        console.print(table)
        return
    eps = get_endpoints(_get_config())
    if not eps:
        console.print("[dim]No endpoints configured in config.yaml[/dim]")
        return

    table = Table(title="Sync Endpoints")
    table.add_column("Name", style="cyan")
    table.add_column("User", style="green")
    table.add_column("Primary IP")
    table.add_column("Secondary IP")
    table.add_column("Path", style="dim")

    for name, ep in eps.items():
        ips = ep.get("ip_address", {})
        table.add_row(
            name,
            ep.get("username", ""),
            ips.get("primary_ip", ""),
            ips.get("secondary_ip", ""),
            ep.get("path", ""),
        )

    console.print(table)


def _structured(peer, db, tier, direction):
    from .replication.coordinator import configured_peers, run
    from .replication.policy import ReplicaError

    peers = configured_peers()
    if peers is None:
        return False
    if peer not in peers:
        raise ReplicaError(
            "Select a peer from memory.sync.peers; remote paths are not accepted"
        )
    if tier != "hot":
        raise ReplicaError(
            "Structured full-tier lifecycle is not integrated yet; no legacy fallback is permitted"
        )
    result = run(peer, direction=direction, db=db)
    console.print_json(data=result)
    if result["cleanup_pending"]:
        raise typer.Exit(2)
    return True


@app.command("serve", hidden=True)
def serve_replica(peer: Annotated[str, typer.Option("--peer")]) -> None:
    """Locally pinned SSH forced-command endpoint."""
    from .replication.server import run

    run(peer)


@app.command("permission")
def replica_permission(
    peer: Annotated[str, typer.Argument(help="Configured memory peer")],
    scope: Annotated[
        str,
        typer.Option("--scope", help="Explicit personal, work or unclassified scope"),
    ],
    action: Annotated[str, typer.Option("--action", help="withdraw or regrant")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Queue an explicit permission change; session-sync delivers it to the peer."""
    from .replication.coordinator import queue_permission

    console.print_json(data=queue_permission(peer, scope, action, db=db))


def main() -> None:
    """Entry point for session-sync CLI."""
    from .replication.policy import ReplicaError
    from .context.scope import ScopeError

    try:
        app()
    except (legacy_guard.LegacySyncRefused, ReplicaError, ScopeError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
