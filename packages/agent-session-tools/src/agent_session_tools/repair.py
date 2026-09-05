"""Local transcript audit/backfill, with dry-run default and an online backup.

Native transcripts are re-read into a disposable snapshot of the target database. This is an exporter
comparison, not an independent proof that the parsers captured every source event.
No source files are modified and no provider APIs are called.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from agent_session_tools.config_loader import get_db_path, load_config
from agent_session_tools.exporters import EXPORTERS, get_exporter

SESSION_COLUMNS = (
    "id",
    "source",
    "project_path",
    "git_branch",
    "created_at",
    "updated_at",
    "metadata",
    "import_fingerprint",
)
MESSAGE_COLUMNS = (
    "id",
    "session_id",
    "role",
    "content",
    "model",
    "timestamp",
    "metadata",
    "seq",
)


@dataclass
class RepairReport:
    mode: str = "native-repair"
    sources: dict = field(default_factory=dict)
    migrations_needed: list[str] = field(default_factory=list)
    migrations_applied: list[str] = field(default_factory=list)
    staged_roles: list[dict] = field(default_factory=list)
    missing_sessions: int = 0
    changed_sessions: int = 0
    missing_messages: int = 0
    changed_messages: int = 0
    retained_messages: int = 0
    removed_messages: int = 0
    preserved_historical_messages: int = 0
    preserved_target_metadata: int = 0
    preserved_target_nonempty: int = 0
    message_revisions: int = 0
    skipped_empty_messages: int = 0
    removed_roles: list[dict] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    applied: bool = False
    backup: str | None = None
    validation: str | None = None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _rows(conn: sqlite3.Connection, table: str, wanted: tuple[str, ...]) -> dict:
    available = _columns(conn, table)
    if "id" not in available:
        return {}
    cols = [col for col in wanted if col in available]
    cursor = conn.execute(f"SELECT {', '.join(cols)} FROM {table}")
    return {row[0]: dict(zip(cols, row, strict=True)) for row in cursor}


def _digest(rows: object) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _snapshot(conn: sqlite3.Connection) -> tuple[dict, dict]:
    return _rows(conn, "sessions", SESSION_COLUMNS), _rows(
        conn, "messages", MESSAGE_COLUMNS
    )


def _different(expected: dict, actual: dict) -> bool:
    return any(actual.get(key) != value for key, value in expected.items())


def compare(stage: sqlite3.Connection, target: sqlite3.Connection) -> RepairReport:
    """Compare exported rows, retaining history absent from native transcripts."""
    from agent_session_tools.migrations import (
        CURRENT_VERSION,
        MIGRATIONS,
        get_user_version,
    )

    report = RepairReport()
    current = get_user_version(target)
    report.migrations_needed = [
        f"v{version}: {MIGRATIONS[version][0]}"
        for version in range(current + 1, CURRENT_VERSION + 1)
        if version in MIGRATIONS
    ]
    expected_sessions, expected_messages = _snapshot(stage)
    sessions, messages = _snapshot(target)
    for ident, row in expected_sessions.items():
        old = sessions.get(ident)
        if old is None:
            report.missing_sessions += 1
        elif old["source"] != row["source"]:
            report.conflicts.append(f"Session {ident} belongs to a different source")
        elif _different(row, old):
            report.changed_sessions += 1
    for ident, row in expected_messages.items():
        old = messages.get(ident)
        if old is None:
            report.missing_messages += 1
        elif old["session_id"] != row["session_id"]:
            report.conflicts.append(f"Message {ident} belongs to a different session")
        elif _different(row, old):
            report.changed_messages += 1
    report.retained_messages = sum(
        row["session_id"] in expected_sessions and ident not in expected_messages
        for ident, row in messages.items()
    )
    return report


def _upsert(conn: sqlite3.Connection, table: str, rows: dict) -> None:
    available = _columns(conn, table)
    for row in rows.values():
        cols = [col for col in row if col in available]
        setters = ", ".join(f"{col}=excluded.{col}" for col in cols if col != "id")
        conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(id) DO UPDATE SET {setters}",
            [row[col] for col in cols],
        )


def apply_staged(
    stage: sqlite3.Connection,
    target_path: Path,
    report: RepairReport,
    *,
    removed_ids: set[str] | None = None,
    baseline_digest: str | None = None,
) -> None:
    """Merge staged evidence; delete only explicitly reconciled native stale rows.

    Compare against the online backup after acquiring the writer lock, so a
    concurrent export between backup and lock acquisition causes a clean abort.
    """
    if report.errors or report.conflicts:
        raise ValueError(
            "Repair blocked: resolve reported exporter errors or identity conflicts"
        )
    if not target_path.is_file():
        raise ValueError(
            "Target database must exist; initialise it with session-export first"
        )
    target = sqlite3.connect(target_path, timeout=30)
    target.execute("PRAGMA foreign_keys=ON")
    backup_path = target_path.with_name(
        target_path.name
        + ".repair-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + ".bak"
    )
    # Exclusive creation and mode 0600 before writing any conversation data.
    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(backup_path) as backup:
            target.backup(backup)
            before = _snapshot(backup)
        report.backup = str(backup_path)
        target.execute("BEGIN IMMEDIATE")
        if _digest(_snapshot(target)) != _digest(before):
            raise ValueError(
                "Database changed during backup; rerun repair after the concurrent export"
            )
        if baseline_digest is not None and _digest(before) != baseline_digest:
            raise ValueError(
                "Database changed during staging; rerun repair during a quiet period"
            )
        from agent_session_tools.migrations import migrate

        applied_migrations = migrate(target)
        fresh = compare(stage, target)
        if fresh.conflicts:
            raise ValueError(
                "Identity conflicts appeared since inspection; rerun without --apply"
            )
        # A changed/shorter native transcript may be a compacted or active source.
        # Never replace an existing conversation with fewer available messages.
        expected_sessions, expected_messages = _snapshot(stage)
        _, old_messages = before
        expected_groups = defaultdict(set)
        old_groups = defaultdict(set)
        for key, row in expected_messages.items():
            expected_groups[row["session_id"]].add(key)
        for key, row in old_messages.items():
            old_groups[row["session_id"]].add(key)
        for ident in expected_sessions:
            expected_ids = expected_groups[ident]
            old_ids = old_groups[ident]
            if (old_ids - expected_ids) - (removed_ids or set()) and (
                _different(expected_sessions[ident], before[0][ident])
                or any(
                    key in old_messages
                    and _different(expected_messages[key], old_messages[key])
                    for key in expected_ids
                )
            ):
                raise ValueError(
                    f"Session {ident} has retained messages and changed IDs/content; manual reconciliation required"
                )
        if removed_ids:
            from agent_session_tools.exporters.base import _message_is_referenced

            for ident in removed_ids:
                if _message_is_referenced(target, ident):
                    raise ValueError(f"Cannot remove referenced stale message {ident}")
                target.execute("DELETE FROM messages WHERE id = ?", (ident,))
        _upsert(
            target,
            "sessions",
            {
                ident: row
                for ident, row in expected_sessions.items()
                if ident not in before[0] or _different(row, before[0][ident])
            },
        )
        _upsert(
            target,
            "messages",
            {
                ident: row
                for ident, row in expected_messages.items()
                if ident not in old_messages or _different(row, old_messages[ident])
            },
        )
        remaining = compare(stage, target)
        if any(
            (
                remaining.missing_sessions,
                remaining.changed_sessions,
                remaining.missing_messages,
                remaining.changed_messages,
                remaining.conflicts,
            )
        ):
            raise ValueError("Post-merge comparison failed; transaction rolled back")
        integrity = target.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite validation failed: {integrity}")
        # Do not blame repair for pre-existing unrelated foreign-key defects.
        prior_fk = set()
        with sqlite3.connect(backup_path) as backup:
            prior_fk = set(backup.execute("PRAGMA foreign_key_check"))
        if set(target.execute("PRAGMA foreign_key_check")) - prior_fk:
            raise ValueError("Repair introduced foreign-key violations")
        target.commit()
        report.applied = True
        report.migrations_applied = applied_migrations
        report.validation = "All staged rows match; SQLite quick_check passed; no new foreign-key violations"
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()


def run_repair(
    target_path: Path,
    sources: list[str],
    apply: bool = False,
    stage_output: Path | None = None,
) -> RepairReport:
    """Audit current-machine native sessions and optionally backfill the target."""
    if not target_path.is_file():
        raise ValueError(f"Database does not exist: {target_path}")
    with tempfile.TemporaryDirectory(prefix="session-repair-") as tmp:
        stage_path = Path(tmp) / "staging.db"
        stage_path.touch(mode=0o600)
        stage = sqlite3.connect(stage_path)
        stage.row_factory = sqlite3.Row
        with sqlite3.connect(target_path.as_uri() + "?mode=ro", uri=True) as target:
            target.backup(stage)
        baseline = _snapshot(stage)
        baseline_digest = _digest(baseline)
        stage.execute("PRAGMA foreign_keys=ON")
        source_results = {}
        errors = []
        try:
            from agent_session_tools.migrations import migrate

            migrate(stage)
            for source in sources:
                exporter = get_exporter(source)
                if isinstance(exporter, type):
                    exporter = exporter()
                try:
                    if not exporter.is_available():
                        source_results[source] = {"available": False}
                        continue
                    with redirect_stdout(sys.stderr):
                        stats = exporter.export_all(stage, incremental=False)
                    source_results[source] = {"available": True, **asdict(stats)}
                    if stats.errors:
                        errors.append(
                            f"{source}: {stats.errors} export error(s); inspect stderr and native source permissions"
                        )
                except Exception as exc:
                    errors.append(f"{source}: {type(exc).__name__}: {exc}")
            stage.commit()
            # A shorter native transcript may be compacted, not authoritative
            # evidence that historical conversation content should disappear.
            staged_messages = _snapshot(stage)[1]
            replacement_budget = Counter(
                (row["session_id"], row["role"], row["content"])
                for ident, row in staged_messages.items()
                if ident not in baseline[1]
            )
            preserved = {}
            removed_roles = Counter()
            for ident in set(baseline[1]) - set(staged_messages):
                row = baseline[1][ident]
                key = (row["session_id"], row["role"], row["content"])
                if row["content"] and str(row["content"]).strip():
                    if replacement_budget[key]:
                        replacement_budget[key] -= 1
                    else:
                        preserved[ident] = row
                        continue
                removed_roles[
                    (row["role"], bool(row["content"] and str(row["content"]).strip()))
                ] += 1
            _upsert(stage, "messages", preserved)
            stage.commit()
            with sqlite3.connect(target_path.as_uri() + "?mode=ro", uri=True) as target:
                target.execute("BEGIN")
                report = compare(stage, target)
            report.sources = source_results
            report.staged_roles = [
                {"source": row[0], "role": row[1], "messages": row[2]}
                for row in stage.execute(
                    "SELECT s.source, m.role, count(*) FROM messages m "
                    "JOIN sessions s ON s.id=m.session_id GROUP BY s.source, m.role"
                )
            ]
            for ident, row in baseline[1].items():
                expected = staged_messages.get(ident)
                if (
                    expected
                    and row["content"]
                    and str(row["content"]).strip()
                    and (
                        expected["content"] != row["content"]
                        or expected["role"] != row["role"]
                    )
                ):
                    errors.append(
                        f"Message {ident}: exporter changed existing nonempty evidence; immutable revision required"
                    )
            report.errors = errors
            report.preserved_historical_messages = len(preserved)
            report.removed_roles = [
                {"role": role, "nonempty": nonempty, "messages": count}
                for (role, nonempty), count in sorted(removed_roles.items())
            ]
            removed_ids = set(baseline[1]) - set(_snapshot(stage)[1])
            report.removed_messages = len(removed_ids)
            report.retained_messages -= len(removed_ids)
            if stage_output is not None:
                if report.errors or report.conflicts:
                    raise ValueError(
                        "Cannot save staging output with export errors or conflicts"
                    )
                fd = os.open(stage_output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                with sqlite3.connect(stage_output) as output:
                    stage.backup(output)
            if apply:
                apply_staged(
                    stage,
                    target_path,
                    report,
                    removed_ids=removed_ids,
                    baseline_digest=baseline_digest,
                )
            return report
        finally:
            stage.close()


def merge_database(
    target_path: Path, source_path: Path, apply: bool = False
) -> RepairReport:
    """Add another database's conversation history; never resolve conflicts by age.

    Native sources are not consulted. Target session metadata and annotations
    remain authoritative; source-only conversation rows retain their metadata.
    """
    if not target_path.is_file() or not source_path.is_file():
        raise ValueError("Both databases must exist")
    if target_path.resolve() == source_path.resolve():
        raise ValueError("Source and target databases must differ")
    with tempfile.TemporaryDirectory(prefix="session-merge-") as tmp:
        stage_path = Path(tmp) / "staging.db"
        stage_path.touch(mode=0o600)
        stage = sqlite3.connect(stage_path)
        try:
            with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
                source.backup(stage)
            if not {"id", "source"} <= _columns(stage, "sessions") or not {
                "id",
                "session_id",
                "role",
                "content",
            } <= _columns(stage, "messages"):
                raise ValueError("Source is not a supported conversation database")
            source_sessions, source_messages = _snapshot(stage)
            with sqlite3.connect(target_path.as_uri() + "?mode=ro", uri=True) as target:
                target.execute("BEGIN")
                target_sessions, target_messages = _snapshot(target)
                baseline_digest = _digest((target_sessions, target_messages))
                # Seed the merge from the target so its annotations, existing
                # message IDs, and richer/longer conversations stay untouched.
                target.backup(stage)
                from agent_session_tools.migrations import migrate

                migrate(stage)
                identity_conflicts = []
                new_sessions = {}
                for ident, row in source_sessions.items():
                    prior = target_sessions.get(ident)
                    if prior is None:
                        new_sessions[ident] = row
                    elif prior["source"] != row["source"]:
                        identity_conflicts.append(
                            f"Session {ident} belongs to a different source"
                        )
                _upsert(stage, "sessions", new_sessions)
                incoming = []
                metadata_kept = 0
                nonempty_kept = 0
                skipped_empty = 0
                for ident, row in source_messages.items():
                    if ident not in target_messages and not (
                        row["content"] and str(row["content"]).strip()
                    ):
                        skipped_empty += 1
                        continue
                    # Revisions imported back from another host can have the
                    # same evidence under the original ID there. Re-resolve
                    # their explicit provenance to avoid roundtrip duplicates.
                    try:
                        metadata = json.loads(row.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        metadata = {}
                    original_id = (
                        metadata.get("source_record_id")
                        if isinstance(metadata, dict)
                        else None
                    )
                    original = (
                        target_messages.get(original_id)
                        if isinstance(original_id, str)
                        else None
                    )
                    if (
                        original
                        and original["session_id"] == row["session_id"]
                        and (
                            ident not in target_messages
                            or target_messages[ident]["session_id"] == row["session_id"]
                        )
                    ):
                        row = {**row, "id": original_id}
                        ident = original_id
                    prior = target_messages.get(ident)
                    if prior and prior["session_id"] != row["session_id"]:
                        identity_conflicts.append(
                            f"Message {ident} belongs to a different session"
                        )
                        continue
                    if (
                        prior
                        and prior["content"]
                        and str(prior["content"]).strip()
                        and not (row["content"] and str(row["content"]).strip())
                    ):
                        nonempty_kept += 1
                        continue
                    if prior and (prior["role"], prior["content"]) == (
                        row["role"],
                        row["content"],
                    ):
                        if _different(row, prior):
                            metadata_kept += 1
                        incoming.append(prior)
                    else:
                        incoming.append(row)
                from agent_session_tools.exporters.base import (
                    _preserve_message_identity,
                )

                revisions = _preserve_message_identity(target, incoming)
                revision_count = sum(
                    old["id"] != new["id"] and new["id"] not in target_messages
                    for old, new in zip(incoming, revisions, strict=True)
                )
                merged = {}
                for row in revisions:
                    prior = target_messages.get(row["id"])
                    if prior:
                        if prior["session_id"] != row["session_id"]:
                            identity_conflicts.append(
                                f"Message {row['id']} belongs to a different session"
                            )
                            continue
                        if (prior["role"], prior["content"]) == (
                            row["role"],
                            row["content"],
                        ):
                            row = prior
                    existing = merged.get(row["id"])
                    if existing and (
                        existing["session_id"],
                        existing["role"],
                        existing["content"],
                    ) != (row["session_id"], row["role"], row["content"]):
                        identity_conflicts.append(
                            f"Message {row['id']} has incompatible incoming revisions"
                        )
                        continue
                    merged[row["id"]] = row
                _upsert(
                    stage,
                    "messages",
                    {
                        ident: row
                        for ident, row in merged.items()
                        if ident not in target_messages
                        or _different(row, target_messages[ident])
                    },
                )
                stage.commit()
                report = compare(stage, target)
                report.conflicts.extend(identity_conflicts)
                report.preserved_target_metadata = metadata_kept
                report.preserved_target_nonempty = nonempty_kept
                report.message_revisions = revision_count
                report.skipped_empty_messages = skipped_empty
            report.mode = "database-merge"
            report.sources = {
                "database": {
                    "sessions": len(source_sessions),
                    "messages": len(source_messages),
                }
            }
            if apply:
                apply_staged(
                    stage, target_path, report, baseline_digest=baseline_digest
                )
            return report
        finally:
            stage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(get_db_path(load_config())))
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(EXPORTERS),
        help="Repeat to select sources; default: all",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up database and apply recovered rows (default: inspect only)",
    )
    parser.add_argument(
        "--from-db",
        type=Path,
        help="Merge conversation history from another SQLite database instead of reading native sources",
    )
    parser.add_argument(
        "--stage-output",
        type=Path,
        help="Save a consistent repaired staging snapshot for inspection or another machine; path must not exist",
    )
    args = parser.parse_args()
    if args.from_db and (args.source or args.stage_output):
        parser.error("--from-db cannot be combined with --source or --stage-output")
    try:
        if args.from_db:
            report = merge_database(
                args.db.expanduser().resolve(),
                args.from_db.expanduser().resolve(),
                args.apply,
            )
        else:
            report = run_repair(
                args.db.expanduser().resolve(),
                args.source or list(EXPORTERS),
                args.apply,
                args.stage_output.expanduser().resolve() if args.stage_output else None,
            )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc), "applied": False}), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(asdict(report), indent=2))
    if report.errors or report.conflicts:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
