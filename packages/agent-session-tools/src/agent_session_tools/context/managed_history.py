"""Permanent lifecycle reconciliation for the configured same-owner full archive.

Canonical intent commits before archive cleanup. This is deliberately not a
multi-database atomic transaction, peer permission protocol, or backup restore.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from ..config_loader import get_db_path, load_config
from ..migrations import CURRENT_VERSION
from ..tiering import get_full_db_path
from .lifecycle import (
    compact,
    forget_session,
    purge_session,
    reconcile_local_retirements,
    selected_records,
)
from .scope import ScopeError, ScopePolicy, active_policy, retirement_selection_sql
from .store import _json

CONTROL_TABLES = (
    "context_tombstones",
    "context_observation_tombstones",
    "context_observation_retired_subjects",
    "context_retirements",
)
MAX_CONTROL_ROWS = 1_000_000
MAX_CONTROL_BYTES = 32 * 1024 * 1024
MAX_CLOSURE_ROUNDS = 16


def protected_database(path):
    """Metadata-only guard against legacy whole-file replacement of modern memory."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return False
    with path.open("rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            return False
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND "
                "name IN ('context_projects','context_retirements','context_replica_denials') LIMIT 1"
            ).fetchone()
        )


def require_query_target(path):
    """Managed full history is read through canonical controls, not as a new main DB."""
    canonical, archive, _ = _configured(load_config())
    requested = Path(path).expanduser().resolve()
    if (
        archive is not None
        and archive != canonical
        and (
            requested == archive
            or (requested.exists() and archive.exists() and requested.samefile(archive))
        )
    ):
        raise ScopeError(
            "Query managed full history through the canonical database; a direct full-DB "
            "override cannot enforce current lifecycle controls"
        )


def _configured(config):
    full = get_full_db_path(config)
    return (
        get_db_path(config).expanduser().resolve(),
        full.expanduser().resolve() if full is not None else None,
        ScopePolicy.from_config(config),
    )


def _open(path):
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)
    try:
        conn.row_factory = sqlite3.Row
        if conn.execute("PRAGMA user_version").fetchone()[0] != CURRENT_VERSION:
            raise ScopeError(
                "Managed history requires the current schema on both stores"
            )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("BEGIN IMMEDIATE")
        return conn
    except BaseException:
        conn.close()
        raise


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def _check(configured, identities):
    if _configured(load_config()) != configured:
        raise ScopeError(
            "Managed history configuration changed; retry with current paths and policy"
        )
    if any(_identity(path) != expected for path, expected in identities.items()):
        raise ScopeError("Managed history database file changed; retry the operation")


def _controls(conn):
    rows, total, size = {}, 0, 0
    for table in CONTROL_TABLES:
        total += conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if total > MAX_CONTROL_ROWS:
            raise ScopeError("Managed retirement history exceeds the row budget")
        values = []
        for row in conn.execute(f"SELECT * FROM {table}"):
            value = tuple(row)
            size += len(_json(value).encode())
            if size > MAX_CONTROL_BYTES:
                raise ScopeError("Managed retirement history exceeds the byte budget")
            values.append(value)
        rows[table] = values
    return rows


def _merge(conn, controls):
    for table, rows in controls.items():
        if table not in CONTROL_TABLES:
            raise ValueError("Unsupported managed control table")
        if rows:
            conn.executemany(
                f"INSERT OR IGNORE INTO {table} VALUES ({','.join('?' for _ in rows[0])})",
                rows,
            )


def _counts(conn):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in CONTROL_TABLES
    )


def _keys(controls):
    return {
        table: {row[:2] if table == "context_retirements" else row[:1] for row in rows}
        for table, rows in controls.items()
    }


def _converge(authority, archive):
    """Discover transitive retirement in either copy before committing intent.

    Control rows are append-only, so unchanged counts after merge and purge prove
    that this round added no retirement identities. Body deletion can reveal more
    dependent identities; those enter the next round before either commit.
    """
    for round_number in range(1, MAX_CLOSURE_ROUNDS + 1):
        before = _counts(authority), _counts(archive)
        _merge(authority, _controls(archive))
        _merge(archive, _controls(authority))
        reconcile_local_retirements(authority)
        reconcile_local_retirements(archive)
        if before == (_counts(authority), _counts(archive)):
            if _keys(_controls(authority)) != _keys(_controls(archive)):
                raise ScopeError(
                    "Managed control identity collision; no phase committed"
                )
            return round_number
    raise ScopeError(
        "Managed retirement closure exceeded its work budget; no phase committed"
    )


def _commit_authority(conn):
    """The recovery boundary: durable intent precedes the archive commit."""
    conn.commit()


def _commit_archive(conn):
    conn.commit()


def _same_controls(path, expected):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        current = _controls(conn)
    return _keys(current) == _keys(expected)


def forget_with_history(session_id, *, apply=False):
    """Authorize a canonical or archive-only session, then persist canonical intent."""
    if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
        raise ValueError("Invalid session identity")
    config = load_config()
    configured = _configured(config)
    canonical, archive, _ = configured
    if archive is not None and (
        canonical == archive or (archive.exists() and canonical.samefile(archive))
    ):
        raise ScopeError("Canonical and full-history databases must be different files")
    policy = active_policy()
    scope = policy.request_scope()
    with closing(_open(canonical)) as authority:
        canonical_identity = {canonical: _identity(canonical)}
        # Always verify the applied canonical policy, including archive-only requests.
        retirement_selection_sql(authority, policy=policy, scope=scope)
        if authority.execute(
            "SELECT 1 FROM sessions WHERE id=?", (session_id,)
        ).fetchone():
            result = forget_session(authority, session_id, apply=apply)
            _check(configured, canonical_identity)
            if apply:
                authority.commit()
            return result
        if archive is None or not archive.is_file() or canonical.samefile(archive):
            raise ScopeError("Session is unavailable in the configured scope")
        identities = {path: _identity(path) for path in (canonical, archive)}
        with closing(_open(archive)) as full:
            clause, values = retirement_selection_sql(full, policy=policy, scope=scope)
            if not full.execute(
                "SELECT 1 FROM sessions s WHERE s.id=? AND " + clause,
                [session_id, *values],
            ).fetchone():
                raise ScopeError("Session is unavailable in the configured scope")
            counts = {
                table: full.execute(
                    f"SELECT count(*) FROM {table} WHERE session_id=?", (session_id,)
                ).fetchone()[0]
                for table in ("messages", "context_evidence")
            }
            with selected_records(full, session_id) as selected:
                counts["learner_records"] = full.execute(
                    f"SELECT count(*) FROM {selected}"
                ).fetchone()[0]
            if apply:
                purge_session(authority, session_id)
            _check(configured, identities)
            if active_policy().request_scope() != scope:
                raise ScopeError("Scope changed during archived forgetting")
            if apply:
                authority.commit()
            return {
                "session_id": session_id,
                "applied": apply,
                "selected_from": "configured_full_history",
                "selected_counts": counts,
                "scope": scope.value,
                "replica_reconciliation": "not_performed",
                "canonical_file_cleanup": "pending" if apply else "not_requested",
                "managed_restore_reconciled": False,
            }


def reconcile_full(*, hot: Path | None = None, config=None):
    """Reconcile permanent controls with the configured full DB; no body transfer.

    Existing archive retirement intent is preserved as well as current canonical
    intent. Permission withdrawal is a separate, explicitly incomplete phase.
    External snapshots/native archives are outside this cleanup operation.
    """
    config = load_config() if config is None else config
    configured = _configured(config)
    canonical, archive, _ = configured
    if archive is None:
        return {
            "configured": False,
            "complete": True,
            "coverage": "no_configured_full_store",
        }
    if hot is not None and hot.expanduser().resolve() != canonical:
        return {
            "configured": archive is not None,
            "complete": False,
            "reason": "noncanonical_override",
        }
    if canonical == archive or (
        canonical.exists() and archive.exists() and canonical.samefile(archive)
    ):
        raise ScopeError("Canonical and full-history databases must be different files")
    if not archive.is_file():
        return {
            "configured": True,
            "complete": False,
            "reason": "full_store_unavailable",
        }
    identities = {path: _identity(path) for path in (canonical, archive)}
    try:
        # Fixed lock order. Only canonical commits first; archive rollback after
        # a crash cannot undo that durable intent. Readers also check canonical
        # controls, so a still-stale archive is not an authority for release.
        with closing(_open(canonical)) as authority, closing(_open(archive)) as full:
            _check(configured, identities)
            rounds = _converge(authority, full)
            controls = _controls(authority)
            _check(configured, identities)
            _commit_authority(authority)
            _check(configured, identities)
            _commit_archive(full)
        _check(configured, identities)
        canonical_cleanup = compact(canonical)
        full_cleanup = compact(archive)
        _check(configured, identities)
        stable = _same_controls(canonical, controls) and _same_controls(
            archive, controls
        )
        complete = canonical_cleanup["complete"] and full_cleanup["complete"] and stable
        return {
            "configured": True,
            "complete": bool(complete),
            "coverage": "permanent_controls_in_canonical_and_configured_full_database",
            "closure_rounds": rounds,
            "canonical_cleanup": canonical_cleanup,
            "full_cleanup": full_cleanup,
            "controls_stable": stable,
            "withdrawal_reconciliation": "not_performed",
            "managed_restore_reconciled": False,
            "sync_complete": False,
        }
    except sqlite3.OperationalError:
        return {
            "configured": True,
            "complete": False,
            "reason": "managed_store_busy_or_unavailable",
        }
