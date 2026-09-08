"""Safety harness for concept-sidecar acceptance on disposable Online Backups.

Follows ``agent_session_tools.ontology_live`` (B2's R7 pattern): every function
operates on a throwaway SQLite Online Backup copy under ``/tmp``, never the
source database directly. The source is opened read-only (``mode=ro``) with its
own read transaction rolled back, and its sentinels are re-read afterwards to
prove the live database was untouched.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..migrations import CURRENT_VERSION, get_user_version, migrate
from ..ontology_live import (
    _create_online_backup,
    _delete_backup,
    _read_source_sentinels,
    _schema_fingerprint,
)
from .concept_schema import (
    SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    _inspect_fts_consistency,
    verify_installed_schema,
)

_BACKUP_PREFIX = "agent-session-tools-concepts-"

SIDECAR_TABLES = (
    "context_concepts",
    "context_concept_events",
    "context_concept_clock",
    "context_concept_fts",
    "context_concept_schema",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def capture_sidecar_receipt(
    conn: sqlite3.Connection,
    *,
    from_version: int,
    to_version: int,
    applied: list[str],
) -> dict[str, Any]:
    """Aggregates-only evidence that a real backup copy installed the sidecar.

    No row content -- counts, the schema DDL fingerprint, and the sidecar's own
    frozen ``SCHEMA_FINGERPRINT`` only; safe to commit to the repository per
    ``docs/data/ontology-migration-v48-receipt.json``'s precedent.
    """
    conn.execute("PRAGMA foreign_keys=ON")
    verify_installed_schema(conn)
    tables = sorted(
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    )
    countable = [
        "sessions",
        "messages",
        "context_assertions",
        "context_concepts",
        "context_concept_events",
    ]
    counts = {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in countable
        if table in tables
    }
    return {
        "evidence_schema": "agent-session-tools.concept-sidecar-migration-receipt",
        "evidence_version": 1,
        "captured_at_utc": _utc_now(),
        "from_version": from_version,
        "to_version": to_version,
        "applied_migrations": applied,
        "schema_sha256": _schema_fingerprint(conn),
        "concept_schema_version": SCHEMA_VERSION,
        "concept_schema_fingerprint": SCHEMA_FINGERPRINT,
        "sidecar_tables_present": [t for t in SIDECAR_TABLES if t in tables],
        "counts": counts,
    }


def run_live_copy_migration_receipt(
    source_path: Path,
    *,
    _backup_dir: Path = Path("/tmp"),
) -> dict[str, Any]:
    """Take an Online Backup of ``source_path``, migrate it, and return a receipt.

    R7 "real upgrade" for v49: proves a genuine production database upgrades
    cleanly to :data:`agent_session_tools.migrations.CURRENT_VERSION` with the
    complete, fingerprint-verified concept sidecar installed, with an
    aggregates-only receipt retained as evidence.
    """
    source = source_path.expanduser()
    if not source.is_file():
        raise RuntimeError("explicit concept-sidecar source is not a file")

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
            fts = _inspect_fts_consistency(conn)
            if not fts.consistent:
                raise RuntimeError("freshly installed concept FTS is inconsistent")
            receipt = capture_sidecar_receipt(
                conn,
                from_version=from_version,
                to_version=to_version,
                applied=applied,
            )
        after = _read_source_sentinels(source)
        if after != before:
            raise RuntimeError("source sentinels changed during sidecar acceptance")
        return receipt
    finally:
        _delete_backup(backup)
