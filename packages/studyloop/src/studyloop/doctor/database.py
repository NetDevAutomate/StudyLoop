"""Database health checks for review DB and sessions DB."""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import TYPE_CHECKING

from studyloop.doctor.models import CheckResult
from studyloop.harnesses import SESSION_SOURCE_BY_HARNESS

if TYPE_CHECKING:
    from pathlib import Path

# Source labels the read paths still surface: one per release harness, plus the
# first-party label `tutor-checkpoint` writes directly (it is a first-party
# *source*, not a harness, so it is absent from SESSION_SOURCE_BY_HARNESS but
# must never be reported as retired).
#
# `agent_session_tools.sources.SUPPORTED_SOURCES` is the same set, derived from
# the exporters' own `source_name` values; a parity test binds the two so they
# cannot drift. Derived here from `SESSION_SOURCE_BY_HARNESS` so this check does
# not depend on that module existing yet.
_SUPPORTED_SOURCES = frozenset(SESSION_SOURCE_BY_HARNESS.values()) | {"study_mentor"}


def _get_review_db_path() -> Path:
    from studyloop.settings import get_db_path

    return get_db_path()


def _get_sessions_db_path() -> Path:
    """Resolve the sessions DB path the same way the rest of the app does.

    Previously this tried ``agent_session_tools.config``, a module that no
    longer exists (it was renamed to ``config_loader``), and fell back to a
    hardcoded ``CONFIG_DIR / "sessions.db"`` on the resulting ImportError. The
    fallback therefore ran *every* time, so ``studyloop doctor`` reported on
    the default database even when ``session_db`` pointed somewhere else —
    a silently wrong health check.

    ``studyloop.settings.get_db_path`` is the single resolver that honours the
    ``session_db`` / ``database.path`` config keys, then ``STUDYLOOP_DB``, then
    the default.
    """
    from studyloop.settings import get_db_path

    return get_db_path()


def check_review_db() -> list[CheckResult]:
    db_path = _get_review_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "database",
                "review_db",
                "warn",
                f"Review DB not found: {db_path}",
                "studyloop review will create it on first use",
                fix_auto=False,
            )
        ]
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA integrity_check")
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        expected = {"card_reviews", "review_sessions"}
        missing = expected - tables
        if missing:
            return [
                CheckResult(
                    "database",
                    "review_db",
                    "fail",
                    f"Review DB missing tables: {', '.join(sorted(missing))}",
                    "studyloop review --rebuild",
                    fix_auto=True,
                )
            ]
        return [
            CheckResult(
                "database",
                "review_db",
                "pass",
                f"Review DB healthy: {db_path}",
                "",
                fix_auto=False,
            )
        ]
    except sqlite3.DatabaseError as exc:
        return [
            CheckResult(
                "database",
                "review_db",
                "fail",
                f"Review DB corrupt: {exc}",
                f"Delete and recreate: rm {db_path}",
                fix_auto=False,
            )
        ]


def check_sessions_db() -> list[CheckResult]:
    spec = importlib.util.find_spec("agent_session_tools")
    if spec is None:
        return [
            CheckResult(
                "database",
                "sessions_db",
                "info",
                "agent-session-tools not installed — sessions DB not checked",
                "studyloop install tools",
                fix_auto=False,
            )
        ]
    db_path = _get_sessions_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "database",
                "sessions_db",
                "warn",
                f"Sessions DB not found: {db_path}",
                "Run any agent session tool to create it",
                fix_auto=False,
            )
        ]
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA integrity_check")
        results = [
            CheckResult(
                "database",
                "sessions_db",
                "pass",
                f"Sessions DB healthy: {db_path}",
                "",
                fix_auto=False,
            )
        ]
        results.extend(_check_fts_drift(conn, db_path))
        results.extend(_check_embeddings_alignment(conn, db_path))
        results.extend(_check_legacy_sources(conn))
        conn.close()
        return results
    except sqlite3.DatabaseError as exc:
        return [
            CheckResult(
                "database",
                "sessions_db",
                "fail",
                f"Sessions DB corrupt: {exc}",
                f"Delete and recreate: rm {db_path}",
                fix_auto=False,
            )
        ]


def _check_legacy_sources(conn: sqlite3.Connection) -> list[CheckResult]:
    """Report sessions stored under retired source labels.

    The live DB holds thousands of sessions exported by adapters that no longer
    exist (aider, kilocode_cli, repoprompt, litellm-proxy, gemini_cli,
    bedrock_proxy, omp). Those rows are **hidden** at the read paths — search and
    list filter to the supported sources — but they are never deleted, because
    the DB is the only surviving copy of most of that history.

    Hidden-and-silent is the dangerous combination: a learner whose session count
    drops has no way to tell scoping from data loss. This makes the scoping
    visible, and says explicitly that nothing was deleted.

    Reported as ``info``: it is a statement of fact with no remedy, so it must
    not affect the exit code or ``doctor --fix`` (see ``_compute_exit_code`` and
    ``_apply_fixes``, which act on ``warn``/``fail`` only).
    """
    placeholders = ", ".join("?" * len(_SUPPORTED_SOURCES))
    try:
        # The only interpolation is the `?` placeholder run; every label is bound.
        # `OR source IS NULL`: the read paths admit rows with `source IN (...)`,
        # which a NULL source never satisfies -- so a NULL row is hidden too and
        # must be counted here, or doctor would under-report what is hidden.
        rows = conn.execute(
            "SELECT source, count(*) FROM sessions "
            f"WHERE source NOT IN ({placeholders}) OR source IS NULL "
            "GROUP BY source ORDER BY 2 DESC",
            sorted(_SUPPORTED_SOURCES),
        ).fetchall()
    except sqlite3.OperationalError:
        # No sessions table / no source column yet (fresh DB) — nothing to check.
        return []

    total = sum(count for _, count in rows)
    if total == 0:
        return [
            CheckResult(
                "database",
                "legacy-sources",
                "pass",
                "no legacy-source sessions",
                "",
                fix_auto=False,
            )
        ]

    breakdown = ", ".join(f"{source or '(null)'} {count:,}" for source, count in rows)
    sessions_word = "session" if total == 1 else "sessions"
    sources_word = "source" if len(rows) == 1 else "sources"
    return [
        CheckResult(
            "database",
            "legacy-sources",
            "info",
            f"{total:,} {sessions_word} in {len(rows)} retired {sources_word} "
            f"(hidden from search, not deleted): {breakdown}",
            "Legacy rows stay for history; they are not searchable. Nothing to fix.",
            fix_auto=False,
        )
    ]


def _check_fts_drift(conn: sqlite3.Connection, db_path: Path) -> list[CheckResult]:
    """Check the FTS invariant: index rows == messages with content.

    A drifting index is the failure mode that once grew a sessions DB to
    45GB (the same 32MB of messages indexed ~586 times by a non-idempotent
    export path). Catch it the day it starts, on every machine.
    """
    try:
        messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE content IS NOT NULL"
        ).fetchone()[0]
        fts_rows = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    except sqlite3.OperationalError:
        # Tables not created yet (fresh DB) — nothing to check.
        return []

    drift = fts_rows - messages
    if drift == 0:
        return [
            CheckResult(
                "database",
                "sessions_fts",
                "pass",
                f"FTS index consistent ({fts_rows:,} rows)",
                "",
                fix_auto=False,
            )
        ]
    # Any drift is an invariant violation; large drift means the index is
    # being duplicated and the DB will bloat without bound.
    severity = "fail" if abs(drift) > max(100, messages // 10) else "warn"
    return [
        CheckResult(
            "database",
            "sessions_fts",
            severity,
            f"FTS index drift: {fts_rows:,} index rows for {messages:,} messages ({drift:+,})",
            "session-maint fts-check --fix",
            # Auto-fixable: `doctor --fix` calls tiering.repair_fts() directly.
            # This was False while the remedy string was still shown, so
            # `doctor --fix` printed the repair command and never ran it.
            fix_auto=True,
        )
    ]


# The two halves of the `semantic` extra. Either one absent means the embed job
# cannot run, so a database with no vectors is a statement of fact rather than a
# fault (design D-8, "loud degradation").
_SEMANTIC_EXTRA_MODULES = ("sentence_transformers", "sqlite_vec")


def _missing_semantic_modules() -> tuple[str, ...]:
    """Which halves of the ``semantic`` extra are absent — without importing them.

    ``find_spec`` rather than a real ``import``: importing
    ``sentence_transformers`` pulls torch and costs seconds, and this runs on
    every ``studyloop doctor``. The condition measured is the same one D-8 names
    (the extra is not installed), just without paying for it.
    """
    missing: list[str] = []
    for name in _SEMANTIC_EXTRA_MODULES:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            # A broken or namespace-shadowed install is "not usable" here.
            found = False
        if not found:
            missing.append(name)
    return tuple(missing)


def _configured_embedding_model() -> tuple[str, int | None]:
    """``(model, dim)`` the alignment report and ``doctor --fix`` must agree on.

    ``dim`` is ``None`` for a model outside ``SUPPORTED_MODELS`` (a hand-set
    ``EMBEDDING_MODEL``), which makes the mismatch check compare the model name
    alone instead of inventing a dimension to compare against. Lives here so the
    check and the fix in ``cli/_doctor.py`` cannot resolve it differently — a
    sweep against a different model than the report counted would delete the
    vectors the report called aligned.
    """
    from agent_session_tools.config_loader import get_embedding_model
    from agent_session_tools.embeddings import SUPPORTED_MODELS

    model = get_embedding_model()
    dimensions = SUPPORTED_MODELS.get(model, {}).get("dimensions")
    return model, dimensions if isinstance(dimensions, int) else None


def _check_embeddings_alignment(conn: sqlite3.Connection, db_path: Path) -> list[CheckResult]:
    """Prove the ``message_embeddings`` invariant with counts rather than trust.

    Migration 48's triggers are what stop a vector outliving the text it
    describes, and the eligibility predicate is what stops a hidden session being
    embedded at all. Those are the mechanisms; this is the proof —
    ``embedding_alignment.alignment_report`` counts five states and this reports
    them.

    Only ``missing`` (the backlog) needs the model to shrink, so it is the one
    state reported as a warning the learner has to act on themselves
    (``session-maint embed``); everything else is plain SQL and
    ``doctor --fix`` does it in-process, exactly as the FTS repair does.
    """
    try:
        from agent_session_tools import embedding_alignment
    except ImportError:
        return []

    model, dim = _configured_embedding_model()
    try:
        report = embedding_alignment.alignment_report(conn, model=model, dim=dim)
    except sqlite3.OperationalError:
        # No message_embeddings table (a database below migration 48) — nothing
        # to check, same disposition as _check_fts_drift on a fresh DB.
        return []

    missing_modules = _missing_semantic_modules()
    if missing_modules and report.rows == 0:
        return [
            CheckResult(
                "database",
                "embeddings_alignment",
                "info",
                f"semantic layer not installed ({', '.join(missing_modules)} missing); "
                f"0 message_embeddings rows, {report.eligible:,} messages eligible",
                "uv tool install 'agent-session-tools[semantic]'",
                fix_auto=False,
            )
        ]

    if report.complete:
        return [
            CheckResult(
                "database",
                "embeddings_alignment",
                "pass",
                f"message_embeddings aligned ({report.rows:,} vectors for "
                f"{report.eligible:,} eligible messages, model {model})",
                "",
                fix_auto=False,
            )
        ]

    if not report.aligned:
        states = ", ".join(
            f"{label} {count:,}"
            for label, count in (
                ("orphaned", report.orphaned),
                ("stale", report.stale),
                ("model_mismatch", report.model_mismatch),
                ("hidden", report.hidden),
            )
            if count
        )
        return [
            CheckResult(
                "database",
                "embeddings_alignment",
                "fail",
                f"message_embeddings misaligned: {states} (of {report.rows:,} vectors)",
                "session-maint embed-check --fix",
                # Auto-fixable: cli/_doctor.py calls embedding_alignment.sweep()
                # directly, then rebuilds the derived sidecar index when the
                # sqlite-vec extension is present.
                fix_auto=True,
            )
        ]

    return [
        CheckResult(
            "database",
            "embeddings_alignment",
            "warn",
            f"message_embeddings backlog: {report.missing:,} of {report.eligible:,} "
            f"eligible messages have no vector for {model}",
            "session-maint embed",
            # NOT auto-fixable: shrinking the backlog means running the model,
            # which doctor must never do on the learner's behalf (D-7).
            fix_auto=False,
        )
    ]
