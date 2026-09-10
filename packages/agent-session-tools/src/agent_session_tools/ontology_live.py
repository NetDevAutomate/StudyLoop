"""Safety harness for ontology acceptance on disposable SQLite Online Backups.

Lifted from SessionWeaver's reference ``session_weaver.ontology_live`` (read-only
lift source, per the phase-2 retrofit design's "Migrations" section and R7's
migration-safety requirements) and extended with an explicit migration step:
this package's databases carry a versioned schema
(``agent_session_tools.migrations``) that SessionWeaver's reference database
does not, so a real v47 database must be brought to v48 on the disposable
backup copy before rebuild/status runs against it.

Every function here operates on a throwaway SQLite Online Backup copy, never
the source database directly -- ``run_live_copy_acceptance`` opens the source
read-only (``mode=ro``) and rolls back its own read transaction, so even a
crash mid-backup cannot leave a write pending against the source.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from .migrations import CURRENT_VERSION, get_user_version, migrate
from .ontology import (
    EXTRACTION_VERSION,
    OntologyBuildResult,
    OntologyStatus,
    ontology_status,
    rebuild_ontology,
)

_EVIDENCE_SCHEMA = "agent-session-tools.ontology-tier1-baseline"
_EVIDENCE_VERSION = 1
_MAX_COLD_REBUILD_SECONDS = 5.0
_BACKUP_PREFIX = "agent-session-tools-ontology-"


@dataclass(frozen=True, slots=True)
class _SourceSentinels:
    schema_version: int
    user_version: int
    session_count: int
    message_count: int
    max_updated_at: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _sentinels_from_connection(conn: sqlite3.Connection) -> _SourceSentinels:
    return _SourceSentinels(
        schema_version=int(conn.execute("PRAGMA schema_version").fetchone()[0]),
        user_version=int(conn.execute("PRAGMA user_version").fetchone()[0]),
        session_count=int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
        message_count=int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
        max_updated_at=conn.execute("SELECT MAX(updated_at) FROM sessions").fetchone()[
            0
        ],
    )


def _read_source_sentinels(source: Path) -> _SourceSentinels:
    with closing(sqlite3.connect(_read_only_uri(source), uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        try:
            return _sentinels_from_connection(conn)
        finally:
            conn.rollback()


def _create_online_backup(source: Path, backup: Path) -> tuple[_SourceSentinels, str]:
    with closing(sqlite3.connect(_read_only_uri(source), uri=True)) as source_conn:
        source_conn.execute("PRAGMA query_only = ON")
        source_conn.execute("BEGIN")
        try:
            sentinels = _sentinels_from_connection(source_conn)
            with closing(sqlite3.connect(backup)) as backup_conn:
                source_conn.backup(backup_conn)
            return sentinels, _sha256(backup)
        finally:
            source_conn.rollback()


def _schema_fingerprint(conn: sqlite3.Connection) -> str:
    """SHA-256 over every schema object's DDL, sorted -- no row content."""
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    text = "\n".join(f"{kind}:{name}:{sql}" for kind, name, sql in rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture_migration_receipt(
    conn: sqlite3.Connection,
    *,
    from_version: int,
    to_version: int,
    applied: list[str],
) -> dict[str, Any]:
    """Aggregates-only evidence that a real backup copy upgraded schema versions.

    No row content, only counts and the schema's own DDL fingerprint -- safe
    to commit to the repository per ``docs/data/ontology-migration-v48-receipt.json``.
    """
    tables = sorted(
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    )
    from .ontology import ONTOLOGY_TABLES

    countable = ["sessions", "messages", *sorted(ONTOLOGY_TABLES & set(tables))]
    counts = {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in countable
        if table in tables
    }
    return {
        "evidence_schema": "agent-session-tools.ontology-migration-receipt",
        "evidence_version": 1,
        "captured_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "from_version": from_version,
        "to_version": to_version,
        "applied_migrations": applied,
        "schema_sha256": _schema_fingerprint(conn),
        "tables": tables,
        "counts": counts,
    }


def _timed_rebuild(
    conn: sqlite3.Connection,
    *,
    incremental: bool,
) -> tuple[OntologyBuildResult, float]:
    started = perf_counter()
    result = rebuild_ontology(conn, incremental=incremental)
    return result, round(perf_counter() - started, 6)


def _validate_acceptance(
    first: OntologyBuildResult,
    first_seconds: float,
    second: OntologyBuildResult,
    incremental: OntologyBuildResult,
    status: OntologyStatus,
) -> None:
    if first.logical_hash != second.logical_hash:
        raise RuntimeError("full rebuild logical hashes differ")
    if first_seconds > _MAX_COLD_REBUILD_SECONDS:
        raise RuntimeError("cold full rebuild exceeded five seconds")
    if incremental.logical_hash != second.logical_hash:
        raise RuntimeError("incremental no-op changed the logical hash")
    if incremental.mode != "incremental" or incremental.fallback_reason is not None:
        raise RuntimeError("incremental no-op unexpectedly fell back")
    if not status.healthy:
        raise RuntimeError("ontology status is unhealthy")
    if status.coverage_ratio < 0.99 or status.missing_sessions:
        raise RuntimeError("ontology session coverage is below acceptance")
    if any(
        (
            status.orphan_session_individuals,
            status.orphan_structural_rows,
            status.foreign_key_violations,
            status.domain_range_violations,
        )
    ):
        raise RuntimeError("ontology integrity diagnostics are nonzero")


def _build_evidence(
    *,
    source: _SourceSentinels,
    source_snapshot_hash: str,
    backup_final_hash: str,
    migration: Mapping[str, Any],
    first: OntologyBuildResult,
    first_seconds: float,
    second: OntologyBuildResult,
    second_seconds: float,
    incremental: OntologyBuildResult,
    incremental_seconds: float,
    status: OntologyStatus,
) -> dict[str, Any]:
    counts = second.counts
    return {
        "evidence_schema": _EVIDENCE_SCHEMA,
        "evidence_version": _EVIDENCE_VERSION,
        "captured_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "extraction_version": EXTRACTION_VERSION,
        "migration": dict(migration),
        "source": {
            "online_backup_sha256": source_snapshot_hash,
            "schema_version": source.schema_version,
            "user_version": source.user_version,
            "session_count": source.session_count,
            "message_count": source.message_count,
        },
        "backup": {
            "post_rebuild_sha256": backup_final_hash,
        },
        "counts": {
            "classes": counts.classes,
            "properties": counts.properties,
            "structural": counts.structural,
            "individuals": counts.individuals,
            "relations": counts.relations,
        },
        "coverage": {
            "covered_sessions": status.covered_sessions,
            "missing_sessions": status.missing_sessions,
            "coverage_ratio": status.coverage_ratio,
        },
        "integrity": {
            "orphan_session_individuals": status.orphan_session_individuals,
            "orphan_structural_rows": status.orphan_structural_rows,
            "foreign_key_violations": status.foreign_key_violations,
            "domain_range_violations": status.domain_range_violations,
        },
        "first_full_rebuild": {
            "logical_hash": first.logical_hash,
            "elapsed_seconds": first_seconds,
        },
        "second_full_rebuild": {
            "logical_hash": second.logical_hash,
            "elapsed_seconds": second_seconds,
        },
        "incremental_rebuild": {
            "logical_hash": incremental.logical_hash,
            "elapsed_seconds": incremental_seconds,
            "mode": incremental.mode,
            "fallback_reason": incremental.fallback_reason,
        },
        "status": {
            "healthy": status.healthy,
            "coverage_at_least_99_percent": status.coverage_ratio >= 0.99,
            "extraction_version_matches": status.extraction_version_matches,
            "source_counts_match": status.source_counts_match,
            "fresh": status.fresh,
            "hash_matches": status.hash_matches,
        },
        "source_sentinels_unchanged": True,
    }


def _delete_backup(backup: Path) -> None:
    for suffix in ("", "-journal", "-shm", "-wal"):
        Path(f"{backup}{suffix}").unlink(missing_ok=True)


def run_live_copy_acceptance(
    source_path: Path,
    *,
    _backup_dir: Path = Path("/tmp"),
) -> dict[str, Any]:
    """Exercise migrate/rebuild/status only on an Online Backup; return sanitized evidence.

    The backup is migrated to :data:`agent_session_tools.migrations.CURRENT_VERSION`
    before any ontology rebuild -- a real production database may still be at
    an older schema version, and rebuild/status assume the current one.
    """
    source = source_path.expanduser()
    if not source.is_file():
        raise RuntimeError("explicit ontology source is not a file")

    file_descriptor, backup_name = tempfile.mkstemp(
        prefix=_BACKUP_PREFIX,
        suffix=".db",
        dir=_backup_dir,
    )
    os.close(file_descriptor)
    backup = Path(backup_name)
    try:
        before, source_snapshot_hash = _create_online_backup(source, backup)
        with closing(sqlite3.connect(backup)) as conn:
            from_version = get_user_version(conn)
            applied = migrate(conn)
            migration_evidence = {
                "from_version": from_version,
                "to_version": get_user_version(conn),
                "applied_count": len(applied),
            }
            first, first_seconds = _timed_rebuild(conn, incremental=False)
            second, second_seconds = _timed_rebuild(conn, incremental=False)
            incremental, incremental_seconds = _timed_rebuild(conn, incremental=True)
            status = ontology_status(conn)
        backup_final_hash = _sha256(backup)

        _validate_acceptance(first, first_seconds, second, incremental, status)
        after = _read_source_sentinels(source)
        if after != before:
            raise RuntimeError("source sentinels changed during ontology acceptance")

        return _build_evidence(
            source=before,
            source_snapshot_hash=source_snapshot_hash,
            backup_final_hash=backup_final_hash,
            migration=migration_evidence,
            first=first,
            first_seconds=first_seconds,
            second=second,
            second_seconds=second_seconds,
            incremental=incremental,
            incremental_seconds=incremental_seconds,
            status=status,
        )
    finally:
        _delete_backup(backup)


def run_live_copy_migration_receipt(
    source_path: Path,
    *,
    _backup_dir: Path = Path("/tmp"),
) -> dict[str, Any]:
    """Take an Online Backup of ``source_path`` and migrate it, returning a receipt.

    Used by the R7 "real upgrade" migration-safety check: proves a genuine
    v47 production database upgrades cleanly to
    :data:`agent_session_tools.migrations.CURRENT_VERSION` (v48), with an
    aggregates-only receipt retained as evidence.
    """
    source = source_path.expanduser()
    if not source.is_file():
        raise RuntimeError("explicit ontology source is not a file")

    file_descriptor, backup_name = tempfile.mkstemp(
        prefix=_BACKUP_PREFIX,
        suffix=".db",
        dir=_backup_dir,
    )
    os.close(file_descriptor)
    backup = Path(backup_name)
    try:
        before, _source_snapshot_hash = _create_online_backup(source, backup)
        with closing(sqlite3.connect(backup)) as conn:
            from_version = get_user_version(conn)
            applied = migrate(conn)
            to_version = get_user_version(conn)
            if to_version != CURRENT_VERSION:
                raise RuntimeError(
                    f"migrated backup did not reach CURRENT_VERSION: {to_version}"
                )
            receipt = capture_migration_receipt(
                conn,
                from_version=from_version,
                to_version=to_version,
                applied=applied,
            )
        after = _read_source_sentinels(source)
        if after != before:
            raise RuntimeError("source sentinels changed during migration acceptance")
        return receipt
    finally:
        _delete_backup(backup)


def write_baseline_evidence(evidence: Mapping[str, Any], output: Path) -> None:
    """Write one deterministic sanitized baseline JSON document."""
    output.write_text(
        json.dumps(dict(evidence), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
