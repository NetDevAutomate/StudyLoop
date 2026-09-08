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


def _okf_tree_sentinel(root: Path) -> tuple[int, str]:
    """(markdown file count, order-independent SHA-256 of every file's bytes)."""
    import hashlib

    entries = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        entries.append(relative + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return len(entries), digest


def _report_counters(report: Any) -> dict[str, int]:
    payload = report.to_dict()
    return {name: value for name, value in payload.items() if name != "errors"}


def run_live_okf_import(
    source_path: Path,
    okf_root: Path,
    *,
    config_path: Path,
    _backup_dir: Path = Path("/tmp"),
) -> dict[str, Any]:
    """Run the full legacy OKF import against a disposable Online Backup.

    Sequence (tasks.md 3.5, mirroring the A3b1 baseline capture): dry run,
    write run, idempotent re-import, integrity reconciliation -- all on the
    backup. The OKF tree is opened read-only by the importer's descriptor
    walk; its sentinel (file count + content digest) and the source
    database's sentinels are asserted unchanged. The returned report contains
    aggregates, hashes and timings only -- no paths, titles, or content.
    """
    import json
    import os as _os
    from time import perf_counter

    from .concepts import ConceptService

    source = source_path.expanduser()
    if not source.is_file():
        raise RuntimeError("explicit OKF-import source is not a file")
    root = okf_root.expanduser()
    if not root.is_dir():
        raise RuntimeError("explicit OKF root is not a directory")

    tree_before = _okf_tree_sentinel(root)

    file_descriptor, backup_name = tempfile.mkstemp(
        prefix=_BACKUP_PREFIX,
        suffix=".db",
        dir=_backup_dir,
    )
    _os.close(file_descriptor)
    backup = Path(backup_name)
    try:
        before, source_snapshot_hash = _create_online_backup(source, backup)
        with closing(sqlite3.connect(backup)) as conn:
            conn.row_factory = sqlite3.Row
            migrate(conn)
            conn.execute("PRAGMA foreign_keys=ON")
            from .scope import ScopePolicy, apply_policy

            config = json.loads(config_path.read_text(encoding="utf-8"))
            apply_policy(
                conn,
                ScopePolicy.from_config(config),
                actor="live-okf-import",
                dry_run=False,
            )
            conn.commit()

        service = ConceptService(backup, prepare_schema=False)
        started = perf_counter()
        dry = service.import_okf(root, actor="live-okf-import", dry_run=True)
        dry_seconds = round(perf_counter() - started, 6)
        started = perf_counter()
        write = service.import_okf(root, actor="live-okf-import", dry_run=False)
        write_seconds = round(perf_counter() - started, 6)
        started = perf_counter()
        reimport = service.import_okf(root, actor="live-okf-import", dry_run=False)
        reimport_seconds = round(perf_counter() - started, 6)

        with closing(sqlite3.connect(backup)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            fts = _inspect_fts_consistency(conn)
            integrity = {
                "concept_roots": conn.execute(
                    "SELECT COUNT(*) FROM context_concepts"
                ).fetchone()[0],
                "legacy_roots": conn.execute(
                    "SELECT COUNT(*) FROM context_concepts "
                    "WHERE binding_state='legacy-unbound'"
                ).fetchone()[0],
                "bound_roots": conn.execute(
                    "SELECT COUNT(*) FROM context_concepts WHERE binding_state='bound'"
                ).fetchone()[0],
                "lifecycle_events": conn.execute(
                    "SELECT COUNT(*) FROM context_concept_events"
                ).fetchone()[0],
                "null_session_legacy_roots": conn.execute(
                    "SELECT COUNT(*) FROM context_concepts "
                    "WHERE binding_state='legacy-unbound' AND source_session_id IS NULL"
                ).fetchone()[0],
                "foreign_key_violations": len(
                    conn.execute("PRAGMA foreign_key_check").fetchall()
                ),
                "fts_consistent": fts.consistent,
                "fts_rows": fts.row_count,
                "fts_sha256": fts.digest,
                "schema_version": SCHEMA_VERSION,
                "schema_fingerprint": SCHEMA_FINGERPRINT,
            }
        import hashlib as _hashlib

        backup_hash_after = _hashlib.sha256(backup.read_bytes()).hexdigest()

        after = _read_source_sentinels(source)
        if after != before:
            raise RuntimeError("source sentinels changed during OKF import")
        tree_after = _okf_tree_sentinel(root)

        return {
            "evidence_schema": "agent-session-tools.legacy-okf-import-report",
            "evidence_version": 1,
            "captured_at_utc": _utc_now(),
            "source": {
                "online_backup_sha256": source_snapshot_hash,
                "user_version": before.user_version,
                "session_count": before.session_count,
                "message_count": before.message_count,
                "okf_markdown_files": tree_before[0],
                "okf_tree_sha256": tree_before[1],
            },
            "backup": {"post_import_sha256": backup_hash_after},
            "dry_run": _report_counters(dry),
            "write": _report_counters(write),
            "idempotent_reimport": _report_counters(reimport),
            "integrity": integrity,
            "timings_seconds": {
                "dry_run": dry_seconds,
                "write": write_seconds,
                "idempotent_reimport": reimport_seconds,
            },
            "okf_source_sentinel_unchanged": tree_after == tree_before,
            "source_sentinels_unchanged": True,
            "status": {
                "dry_run_write_classification_matches": all(
                    _report_counters(dry)[key] == _report_counters(write)[key]
                    for key in (
                        "scanned",
                        "parsed",
                        "invalid_yaml",
                        "invalid_schema",
                        "unsafe_path",
                        "duplicate_content",
                        "bound",
                        "legacy_unbound",
                        "missing_session",
                        "no_visible_evidence",
                        "no_exact_match",
                        "ambiguous_match",
                        "oversized_evidence",
                    )
                ),
                "idempotent_reimport": (
                    _report_counters(reimport)["already_present"]
                    == _report_counters(write)["parsed"]
                    - _report_counters(write)["duplicate_content"]
                    and _report_counters(reimport)["writes"] == 0
                ),
                "all_parseable_records_survived": (
                    integrity["concept_roots"] >= _report_counters(write)["imported"]
                ),
            },
        }
    finally:
        _delete_backup(backup)
