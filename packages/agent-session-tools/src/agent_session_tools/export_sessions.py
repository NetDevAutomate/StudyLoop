#!/usr/bin/env python3
"""Export sessions from AI coding CLI tools to unified SQLite database.

Supported sources:
- Claude Code (~/.claude/projects/)
- Codex (~/.codex/sessions/)
- Kiro CLI (~/Library/Application Support/kiro-cli/)
- OpenCode (~/.local/share/opencode/storage/)
- pi coding agent (~/.pi/agent/sessions/)
"""

import logging
import shutil
import sqlite3
from collections.abc import Collection
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from agent_session_tools import ontology
from agent_session_tools.config_loader import (
    get_db_path,
    get_obsidian_config,
    load_config,
)
from agent_session_tools.exporters import (
    EXPORTERS,
    ExportStats,
    get_exporter,
)
from agent_session_tools.migrations import migrate
from agent_session_tools import obsidian_writer

logger = logging.getLogger(__name__)

# Create Typer app with completion support
app = typer.Typer(
    name="session-export",
    help="Export AI coding assistant sessions to SQLite database.",
    add_completion=True,
    rich_markup_mode="rich",
)

# Try to import Rich progress bars
try:
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
    )

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Load configuration
config = load_config()

# Source directories
CLAUDE_DIR = Path.home() / ".claude"
KIRO_DB = Path.home() / "Library/Application Support/kiro-cli/data.sqlite3"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
DEFAULT_DB = get_db_path(config)


def _reconcile_legacy_base_tables(conn: sqlite3.Connection) -> None:
    """Add columns the current schema expects to tables that predate them.

    ``schema.sql`` creates tables with IF NOT EXISTS, so a legacy database's
    tables are kept as-is — but the script's CREATE INDEX statements (and
    several migrations') then reference columns the legacy shape never had
    (e.g. ``sessions.project_path``, ``study_sessions.topic``), and one
    failing statement aborts the whole bootstrap. Historically that failure
    was tolerated (logged, lazy bootstraps carried on); the context-memory
    read paths now genuinely need the full schema, so the legacy shape must
    converge instead.

    Builds the pristine final shape (schema.sql + every migration) in memory,
    diffs each pre-existing live table against it, and ADDs the missing
    columns — nullable, with the schema's default when it is a constant
    (SQLite cannot add a column with a non-constant default, nor
    retroactively enforce NOT NULL/PRIMARY KEY on a populated table).
    Migrations themselves are column-guarded, so replaying them over the
    reconciled shape is safe; tables the bootstrap will create from scratch
    are skipped. Existing rows are never touched.
    """
    pristine = sqlite3.connect(":memory:")
    try:
        with open(SCHEMA_FILE) as f:
            pristine.executescript(f.read())
        migrate(pristine)
        tables = [
            row[0]
            for row in pristine.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        for table in tables:
            live = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if not live:
                continue  # not in the legacy DB; the bootstrap creates it whole
            for _, name, ctype, _, default, pk in pristine.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall():
                if name in live or pk:
                    continue
                ddl = f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ctype}'
                if default is not None and "(" not in str(default):
                    ddl += f" DEFAULT {default}"
                conn.execute(ddl)
    finally:
        pristine.close()


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize database with schema and run migrations."""
    import os

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path.resolve().as_uri(), uri=True)
    conn.row_factory = sqlite3.Row

    # Restrict permissions — session data may contain sensitive conversations
    os.chmod(path, 0o600)

    # Enable WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    # Bring any legacy-shaped base tables up to what schema.sql references
    _reconcile_legacy_base_tables(conn)

    # Apply base schema
    with open(SCHEMA_FILE) as f:
        conn.executescript(f.read())

    # Run any pending migrations
    applied = migrate(conn)
    if applied:
        print(f"Applied {len(applied)} database migration(s)")

    return conn


def create_progress_bar() -> Progress | None:
    """Create a Rich progress bar if available."""
    if not RICH_AVAILABLE:
        return None

    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        TimeRemainingColumn(),
        console=None,  # Use default console
    )


# Valid source choices for CLI
SOURCE_CHOICES = [
    "claude",
    "codex",
    "grok",
    "kiro",
    "opencode",
    "pi",
]


def refresh_ontology_after_export(
    conn: sqlite3.Connection,
    session_ids: Collection[str],
    *,
    incremental: bool = True,
) -> ontology.OntologyBuildResult:
    """Named, monkeypatchable seam: refresh the tier-1 ontology after an export.

    Called from :func:`_run_export` after its per-source export loop commits
    captured session/message rows — never inside that transaction (design:
    "Refresh-failure seam for B2"). ``session_ids`` documents the sessions
    this run touched for observability; the incremental algorithm itself
    (:func:`agent_session_tools.ontology.rebuild_ontology`) independently
    scopes its own candidate set from ``sessions.updated_at``, so a caller
    passing an empty or approximate set still gets a correct refresh.

    A full export (``session-export --full``, ``incremental=False`` here)
    refreshes the whole corpus rather than only a delta, per the
    session-export spec's "A full export run refreshes the whole corpus"
    scenario.
    """
    del session_ids  # observability only; see docstring.
    return ontology.rebuild_ontology(conn, incremental=incremental)


def _run_export(
    output_path: Path,
    sources: set[str],
    incremental: bool,
    obsidian: bool | None = None,
    obsidian_vault: Path | None = None,
    obsidian_backfill: bool = False,
    obsidian_dry_run: bool = False,
) -> dict[str, Any]:
    """Core export logic shared by all entry points.

    Returns a summary dict. Currently the only consumer-facing key is
    ``ontology_refresh`` — the outcome of the post-commit ontology-refresh
    hook — kept minimal rather than duplicating everything already printed
    to stdout.
    """
    print(f"Exporting to: {output_path}")
    conn = init_db(str(output_path))

    # Snapshot (id -> updated_at) before export so we can cheaply identify the
    # sessions actually touched this run — for a targeted Obsidian export and
    # for the ontology-refresh hook below. Two lightweight queries beat
    # re-hashing every session on every incremental run.
    pre_export_state: dict[str, str] = {
        row["id"]: row["updated_at"]
        for row in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
    }

    # Track aggregate stats and one verification receipt per requested source.
    batch_stats = ExportStats(added=0, updated=0, skipped=0, errors=0)
    source_outcomes: dict[str, ExportStats | None] = {}

    # Export each source with progress bars
    progress = create_progress_bar() if len(sources) > 1 else None

    with progress or nullcontext():
        task = (
            progress.add_task("Exporting...", total=len(sources)) if progress else None
        )

        for source in sources:
            source_stats = None
            if source in EXPORTERS:
                exporter = get_exporter(source)
                source_stats = exporter.export_all(conn, incremental)

            # Capture per-source values before accumulating into batch totals
            source_added = 0
            source_updated = 0
            if source_stats:
                if isinstance(source_stats, dict):
                    source_stats = ExportStats(**source_stats)
                source_added = source_stats.added
                source_updated = source_stats.updated
                batch_stats += source_stats

            source_outcomes[source] = source_stats
            if progress and task is not None:
                progress.update(
                    task,
                    description=f"{source.title()}: +{source_added} added, +{source_updated} updated",
                )
                progress.advance(task)

    source_labels = {"claude": "claude_code", "kiro": "kiro_cli"}
    completed_at = datetime.now(UTC).isoformat()
    verification: dict[str, bool] = {}
    for source, outcome in source_outcomes.items():
        stored_source = source_labels.get(source, source)
        sessions_seen = conn.execute(
            "SELECT count(*) FROM sessions WHERE source=?", (stored_source,)
        ).fetchone()[0]
        messages_seen = conn.execute(
            "SELECT count(*) FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE s.source=?",
            (stored_source,),
        ).fetchone()[0]
        errors = outcome.errors if outcome is not None else 1
        verified = outcome is not None and errors == 0
        conn.execute(
            """INSERT INTO session_export_runs
            (source,completed_at,sessions_seen,messages_seen,errors,verified)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(source) DO UPDATE SET
              completed_at=excluded.completed_at,
              sessions_seen=excluded.sessions_seen,
              messages_seen=excluded.messages_seen,
              errors=excluded.errors,
              verified=excluded.verified""",
            (
                source,
                completed_at,
                sessions_seen,
                messages_seen,
                errors,
                int(verified),
            ),
        )
        verification[source] = verified

    # Final commit includes both captured rows and their verification receipts.
    conn.commit()

    # Ontology refresh: after, never inside, the transaction that just
    # committed captured sessions -- a refresh failure here must not roll
    # back or otherwise affect what was just captured (design: "Refresh-
    # failure seam for B2"; EXECUTION-ERRATA.md #7, "session capture is
    # authoritative"). Scoped to the sessions this run touched; a full run
    # refreshes the whole corpus (see refresh_ontology_after_export).
    touched_session_ids = [
        row["id"]
        for row in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
        if pre_export_state.get(row["id"]) != row["updated_at"]
    ]
    ontology_refresh: dict[str, Any]
    try:
        result = refresh_ontology_after_export(
            conn, touched_session_ids, incremental=incremental
        )
        ontology_refresh = {
            "status": "ok",
            "mode": result.mode,
            "fallback_reason": result.fallback_reason,
            "candidate_sessions": result.candidate_sessions,
        }
    except Exception as exc:  # noqa: BLE001 - must never fail the capture
        logger.warning(
            "ontology refresh failed after export: %s: %s",
            type(exc).__name__,
            exc,
            extra={
                "event": "ontology_refresh_failed",
                "error_class": type(exc).__name__,
            },
        )
        ontology_refresh = {"status": "failed", "error_class": type(exc).__name__}

    print("\nExport results:")
    print(f"  added:   {batch_stats.added}")
    print(f"  updated: {batch_stats.updated}")
    print(f"  skipped: {batch_stats.skipped} (unchanged since last export)")
    print(
        f"  empty:   {batch_stats.empty} (no supported conversation or native records)"
    )
    if batch_stats.forgotten:
        print(f"  retired: {batch_stats.forgotten} (excluded by forgetting policy)")
    if batch_stats.errors:
        print(f"  errors:  {batch_stats.errors}")
    if incremental and batch_stats.skipped:
        print(
            "\nnote: 'skipped' = sessions already up-to-date since last export; "
            "re-run with --full to force a full re-import."
        )

    # Stats
    stats = conn.execute(
        """
        SELECT source, COUNT(*) as sessions,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id IN
                (SELECT id FROM sessions s2 WHERE s2.source = s.source)) as messages
        FROM sessions s GROUP BY source
    """
    ).fetchall()

    print("\nDatabase stats:")
    for row in stats:
        print(
            f"  {row['source']}: {row['sessions']} sessions, {row['messages']} messages"
        )

    # ---------------------------------------------------------------------------
    # Obsidian vault export (after DB commit, before close)
    # ---------------------------------------------------------------------------
    cfg = get_obsidian_config()

    # Resolve enabled: explicit CLI flag wins; fall back to config gate.
    enabled: bool
    if obsidian is not None:
        enabled = obsidian
    else:
        enabled = bool(cfg.get("export_enabled", False))

    if enabled:
        # Resolve vault path: CLI flag > config > DEFAULT_CONFIG fallback.
        if obsidian_vault is not None:
            vault_path = obsidian_vault
        else:
            vault_path = Path(
                cfg.get("vault_path", str(Path.home() / "Obsidian" / "Personal"))
            )

        # session_ids determination:
        # - --obsidian-backfill: pass None so the writer exports every session
        #   (idempotent; unchanged notes are skipped). This is the one-time
        #   "import all history" path.
        # - normal run: export only the sessions actually added/updated this
        #   run, computed by diffing the pre-export (id -> updated_at) snapshot
        #   against current state. Avoids scanning + hashing all ~N sessions on
        #   every incremental export.
        session_ids: list[str] | None
        if obsidian_backfill:
            session_ids = None
        else:
            post_export_state = {
                row["id"]: row["updated_at"]
                for row in conn.execute(
                    "SELECT id, updated_at FROM sessions"
                ).fetchall()
            }
            session_ids = [
                sid
                for sid, updated in post_export_state.items()
                if pre_export_state.get(sid) != updated
            ]
            if not session_ids:
                # Nothing changed this run — skip the writer entirely.
                print("\nObsidian export: no new or updated sessions this run.")
                conn.close()
                return {
                    "ontology_refresh": ontology_refresh,
                    "export_verification": verification,
                }

        counts = obsidian_writer.write_vault_notes(
            conn,
            cfg,
            vault_path,
            session_ids=session_ids,
            dry_run=obsidian_dry_run,
        )
        dry_tag = " (dry-run)" if obsidian_dry_run else ""
        print(
            f"\nObsidian export{dry_tag}: "
            f"written={counts['written']}, skipped={counts['skipped']}, mocs={counts['mocs']}"
        )

    conn.close()

    # Tiering: every export triggers a background incremental sync of the
    # hot DB into the configured full DB (cadence per database.sync_mode).
    # No-op when tiering is disabled or the target volume is unmounted —
    # the stateless content-hash diff catches up automatically on remount.
    from agent_session_tools.tiering import maybe_spawn_sync

    if maybe_spawn_sync():
        print("↻ Incremental sync to full DB started in background.")

    return {
        "ontology_refresh": ontology_refresh,
        "export_verification": verification,
    }


@app.command()
def export(
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="Output database path (default: from config)"
        ),
    ] = None,
    # Source selection flags (mutually exclusive behavior handled in code)
    claude_only: Annotated[
        bool, typer.Option("--claude-only", help="Only export Claude Code")
    ] = False,
    codex_only: Annotated[
        bool, typer.Option("--codex-only", help="Only export OpenAI Codex CLI")
    ] = False,
    grok_only: Annotated[
        bool, typer.Option("--grok-only", help="Only export Grok CLI")
    ] = False,
    kiro_only: Annotated[
        bool, typer.Option("--kiro-only", help="Only export Kiro CLI")
    ] = False,
    opencode_only: Annotated[
        bool, typer.Option("--opencode-only", help="Only export OpenCode CLI")
    ] = False,
    pi_only: Annotated[
        bool, typer.Option("--pi-only", help="Only export pi coding agent")
    ] = False,
    sources: Annotated[
        list[str] | None,
        typer.Option(
            "--sources",
            help=f"Export specific sources ({', '.join(SOURCE_CHOICES)})",
        ),
    ] = None,
    # Safety options
    dated: Annotated[
        bool, typer.Option("--dated", help="Append date suffix to output filename")
    ] = False,
    backup: Annotated[
        bool,
        typer.Option(
            "--backup", help="Create backup of existing database before export"
        ),
    ] = False,
    # Export mode
    full: Annotated[
        bool,
        typer.Option("--full", help="Re-import all files, ignoring change detection"),
    ] = False,
    # Obsidian vault export options
    obsidian: Annotated[
        bool | None,
        typer.Option(
            "--obsidian/--no-obsidian",
            help=(
                "Enable or disable Obsidian vault export for this run. "
                "Overrides the export_enabled config gate. "
                "Omit to use the config setting."
            ),
        ),
    ] = None,
    obsidian_vault: Annotated[
        Path | None,
        typer.Option(
            "--obsidian-vault",
            help="Override the Obsidian vault path for this run.",
            exists=False,  # allow non-existent paths; writer handles the guard
        ),
    ] = None,
    obsidian_backfill: Annotated[
        bool,
        typer.Option(
            "--obsidian-backfill",
            help="Export all historical sessions to the vault (batched, idempotent).",
        ),
    ] = False,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify",
            help="Fail unless every requested source records a successful export receipt.",
        ),
    ] = False,
    obsidian_dry_run: Annotated[
        bool,
        typer.Option(
            "--obsidian-dry-run",
            help="Print what would be written to the vault without writing any files.",
        ),
    ] = False,
) -> None:
    """Export AI coding assistant sessions to SQLite database.

    Supported sources:
    - claude_code: Claude Code (~/.claude/projects/)
    - codex: Codex (~/.codex/sessions/)
    - kiro_cli: Kiro CLI (~/Library/Application Support/kiro-cli/)
    - opencode: OpenCode CLI (~/.local/share/opencode/storage/)
    - pi: pi coding agent (~/.pi/agent/sessions/)

    Examples:
        session-export                          # Export all sources
        session-export --claude-only            # Only Claude Code
        session-export --sources opencode --sources pi  # Specific sources
        session-export --dated --backup         # Dated output with backup
        session-export --obsidian               # Also write Obsidian vault notes
        session-export --obsidian --obsidian-dry-run  # Preview vault export
        session-export --obsidian --obsidian-backfill  # Backfill all history
        session-export --obsidian --obsidian-vault ~/MyVault  # Custom vault path
    """
    output_path = Path(output) if output else DEFAULT_DB
    if dated:
        output_path = output_path.with_stem(
            f"{output_path.stem}_{datetime.now():%Y-%m-%d}"
        )

    if backup and output_path.exists():
        backup_path = output_path.with_suffix(f".backup{output_path.suffix}")
        shutil.copy2(output_path, backup_path)
        print(f"Created backup: {backup_path}")

    # Determine which sources to export
    only_flags = {
        "claude": claude_only,
        "codex": codex_only,
        "grok": grok_only,
        "kiro": kiro_only,
        "opencode": opencode_only,
        "pi": pi_only,
    }
    active = [k for k, v in only_flags.items() if v]
    if len(active) > 1:
        raise typer.BadParameter("Only one --*-only flag can be specified at a time")

    if active:
        export_sources = {active[0]}
    elif sources:
        invalid = set(sources) - set(SOURCE_CHOICES)
        if invalid:
            raise typer.BadParameter(
                f"Invalid sources: {invalid}. Valid choices: {SOURCE_CHOICES}"
            )
        export_sources = set(sources)
    else:
        export_sources = set(SOURCE_CHOICES)

    incremental = not full
    summary = _run_export(
        output_path,
        export_sources,
        incremental,
        obsidian=obsidian,
        obsidian_vault=obsidian_vault,
        obsidian_backfill=obsidian_backfill,
        obsidian_dry_run=obsidian_dry_run,
    )
    if verify and not all(summary["export_verification"].values()):
        failed = sorted(
            source for source, ok in summary["export_verification"].items() if not ok
        )
        raise typer.Exit(code=1 if failed else 0)


def main() -> int:
    """Console-script entry point.

    Delegates to the Typer ``app`` so CLI arguments are parsed. The
    ``[project.scripts]`` entry point targets this wrapper, NOT the
    ``@app.command()``-decorated ``export`` function — calling a decorated
    command object directly bypasses Typer's argument parsing entirely
    (every option silently falls back to its default).
    """
    app()
    return 0


if __name__ == "__main__":
    main()
