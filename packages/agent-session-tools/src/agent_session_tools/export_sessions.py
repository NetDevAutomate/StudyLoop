#!/usr/bin/env python3
"""Export sessions from AI coding CLI tools to unified SQLite database.

Supported sources:
- Claude Code (~/.claude/projects/)
- Kiro CLI (~/Library/Application Support/kiro-cli/)
- Gemini CLI (~/.gemini/tmp/)
- Kilocode CLI (~/.kilocode/cli/)
- Aider (.aider.chat.history.md files)
- pi coding agent (~/.pi/agent/sessions/)
- oh-my-pi (omp) (~/.omp/agent/sessions/)
"""

import shutil
import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import (
    get_db_path,
    get_obsidian_config,
    load_config,
)
from agent_session_tools.exporters import (
    EXPORTERS,
    AiderExporter,
    ExportStats,
    get_exporter,
)
from agent_session_tools.migrations import migrate
from agent_session_tools import obsidian_writer

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
GEMINI_DIR = Path.home() / ".gemini" / "tmp"
KILOCODE_DIR = Path.home() / ".kilocode" / "cli"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
DEFAULT_DB = get_db_path(config)


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize database with schema and run migrations."""
    import os

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Restrict permissions — session data may contain sensitive conversations
    os.chmod(path, 0o600)

    # Enable WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

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


def export_aider(
    conn: sqlite3.Connection, incremental: bool = True, args=None
) -> ExportStats:
    """Export Aider sessions using modular exporter."""
    aider_exporter = get_exporter("aider")
    if args and hasattr(args, "aider_paths") and args.aider_paths:
        aider_exporter = AiderExporter(args.aider_paths)
    return aider_exporter.export_all(conn, incremental)


# Valid source choices for CLI
SOURCE_CHOICES = [
    "aider",
    "bedrock",
    "claude",
    "codex",
    "gemini",
    "grok",
    "kilocode",
    "kiro",
    "omp",
    "opencode",
    "pi",
    "repoprompt",
]


def _run_export(
    output_path: Path,
    sources: set[str],
    incremental: bool,
    aider_paths: list[Path] | None = None,
    obsidian: bool | None = None,
    obsidian_vault: Path | None = None,
    obsidian_backfill: bool = False,
    obsidian_dry_run: bool = False,
) -> None:
    """Core export logic shared by all entry points."""
    print(f"Exporting to: {output_path}")
    conn = init_db(str(output_path))

    # Snapshot (id -> updated_at) before export so we can cheaply identify the
    # sessions actually touched this run for a targeted Obsidian export. Two
    # lightweight queries beat re-hashing every session on every incremental run.
    pre_export_state: dict[str, str] = {}
    if obsidian or (obsidian is None):
        # Only pay for the snapshot when Obsidian export might run. The config
        # gate is re-checked after commit; this is a conservative pre-pass.
        pre_export_state = {
            row["id"]: row["updated_at"]
            for row in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
        }

    # Track aggregate stats
    batch_stats = ExportStats(added=0, updated=0, skipped=0, errors=0)

    # Export each source with progress bars
    progress = create_progress_bar() if len(sources) > 1 else None

    with progress or nullcontext():
        task = (
            progress.add_task("Exporting...", total=len(sources)) if progress else None
        )

        for source in sources:
            source_stats = None
            if source == "aider":

                class AiderArgs:
                    aider_paths: list[Path] | None = None

                args = AiderArgs()
                args.aider_paths = aider_paths
                source_stats = export_aider(conn, incremental, args)
            elif source in EXPORTERS:
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

            if progress and task is not None:
                progress.update(
                    task,
                    description=f"{source.title()}: +{source_added} added, +{source_updated} updated",
                )
                progress.advance(task)

    # Final commit
    conn.commit()
    print("\nExport results:")
    print(f"  added:   {batch_stats.added}")
    print(f"  updated: {batch_stats.updated}")
    print(f"  skipped: {batch_stats.skipped} (unchanged since last export)")
    print(f"  empty:   {batch_stats.empty} (no extractable messages)")
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
                return

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
    kiro_only: Annotated[
        bool, typer.Option("--kiro-only", help="Only export Kiro CLI")
    ] = False,
    gemini_only: Annotated[
        bool, typer.Option("--gemini-only", help="Only export Gemini CLI")
    ] = False,
    grok_only: Annotated[
        bool, typer.Option("--grok-only", help="Only export Grok CLI")
    ] = False,
    kilocode_only: Annotated[
        bool, typer.Option("--kilocode-only", help="Only export Kilocode CLI")
    ] = False,
    pi_only: Annotated[
        bool, typer.Option("--pi-only", help="Only export pi coding agent")
    ] = False,
    omp_only: Annotated[
        bool, typer.Option("--omp-only", help="Only export oh-my-pi (omp)")
    ] = False,
    sources: Annotated[
        list[str] | None,
        typer.Option(
            "--sources",
            help=f"Export specific sources ({', '.join(SOURCE_CHOICES)})",
        ),
    ] = None,
    # Aider-specific options
    aider_paths: Annotated[
        list[Path] | None,
        typer.Option(
            "--aider-paths", help="Additional paths to search for Aider history files"
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
    - kiro_cli: Kiro CLI (~/Library/Application Support/kiro-cli/)
    - gemini_cli: Gemini CLI (~/.gemini/tmp/)
    - grok: Grok CLI (~/.grok/sessions/)
    - kilocode_cli: Kilocode CLI (~/.kilocode/cli/)
    - opencode: OpenCode CLI (~/.local/share/opencode/storage/)
    - repoprompt: RepoPrompt (~/Library/Application Support/RepoPrompt/)
    - pi: pi coding agent (~/.pi/agent/sessions/)
    - omp: oh-my-pi (omp) (~/.omp/agent/sessions/)

    Examples:
        session-export                          # Export all sources
        session-export --claude-only            # Only Claude Code
        session-export --sources gemini opencode  # Specific sources
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
        "kiro": kiro_only,
        "gemini": gemini_only,
        "grok": grok_only,
        "kilocode": kilocode_only,
        "pi": pi_only,
        "omp": omp_only,
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
    _run_export(
        output_path,
        export_sources,
        incremental,
        aider_paths,
        obsidian=obsidian,
        obsidian_vault=obsidian_vault,
        obsidian_backfill=obsidian_backfill,
        obsidian_dry_run=obsidian_dry_run,
    )


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
