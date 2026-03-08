#!/usr/bin/env python3
"""Export sessions from AI coding CLI tools to unified SQLite database.

Supported sources:
- Claude Code (~/.claude/projects/)
- Kiro CLI (~/Library/Application Support/kiro-cli/)
- Gemini CLI (~/.gemini/tmp/)
- Kilocode CLI (~/.kilocode/cli/)
- Aider (.aider.chat.history.md files)
"""

import hashlib
import shutil
import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import get_db_path, load_config
from agent_session_tools.exporters import EXPORTERS, AiderExporter, ExportStats, get_exporter
from agent_session_tools.migrations import migrate

# Create Typer app with completion support
app = typer.Typer(
    name="session-export",
    help="Export AI coding assistant sessions to SQLite database.",
    add_completion=True,
    rich_markup_mode="rich",
)

# Try to import Rich progress bars
try:
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

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


def stable_id(prefix: str, key: str) -> str:
    """Generate stable, deterministic ID from prefix and key.

    Uses SHA256 instead of Python's hash() which changes per process.
    """
    normalized = str(Path(key).resolve()).lower()
    hash_bytes = hashlib.sha256(normalized.encode()).hexdigest()[:12]
    return f"{prefix}_{hash_bytes}"


def content_hash(content: str) -> str:
    """Generate hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def file_fingerprint(file_path: Path) -> str:
    """Generate fingerprint from file metadata for change detection."""
    stat = file_path.stat()
    return f"{stat.st_mtime}:{stat.st_size}"


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


def commit_batch(
    conn: sqlite3.Connection, sessions: list, messages: list, stats: ExportStats
) -> None:
    """Commit a batch of sessions and messages to the database."""
    if not sessions:
        return

    try:
        # Bulk insert sessions
        conn.executemany(
            """
            INSERT OR REPLACE INTO sessions (
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    s["id"],
                    s["source"],
                    s["project_path"],
                    s["git_branch"],
                    s["created_at"],
                    s["updated_at"],
                    s["metadata"],
                )
                for s in sessions
            ],
        )

        # Bulk insert messages
        conn.executemany(
            """
            INSERT OR REPLACE INTO messages (
                id, session_id, role, content, model, timestamp, metadata, seq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    m["id"],
                    m["session_id"],
                    m["role"],
                    m["content"],
                    m["model"],
                    m["timestamp"],
                    m["metadata"],
                    m["seq"],
                )
                for m in messages
            ],
        )

        # Update stats
        stats.added += len([s for s in sessions if s["status"] == "added"])
        stats.updated += len([s for s in sessions if s["status"] == "updated"])
        stats.skipped += len([s for s in sessions if s["status"] == "skipped"])

    except sqlite3.Error as e:
        stats.errors += len(sessions)
        print(f"❌ Batch commit failed: {e}")
        conn.rollback()
    else:
        conn.commit()


def export_aider(conn: sqlite3.Connection, incremental: bool = True, args=None) -> ExportStats:
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
    "gemini",
    "kilocode",
    "kiro",
    "opencode",
    "repoprompt",
]


def _run_export(
    output_path: Path,
    sources: set[str],
    incremental: bool,
    aider_paths: list[Path] | None = None,
) -> None:
    """Core export logic shared by all entry points."""
    print(f"Exporting to: {output_path}")
    conn = init_db(str(output_path))

    # Track aggregate stats
    batch_stats = ExportStats(added=0, updated=0, skipped=0, errors=0)

    # Export each source with progress bars
    progress = create_progress_bar() if len(sources) > 1 else None

    with progress or nullcontext():
        task = progress.add_task("Exporting...", total=len(sources)) if progress else None

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

            # Accumulate batch stats
            if source_stats:
                if isinstance(source_stats, dict):
                    batch_stats.added += source_stats.get("added", 0)
                    batch_stats.updated += source_stats.get("updated", 0)
                    batch_stats.skipped += source_stats.get("skipped", 0)
                    batch_stats.errors += source_stats.get("errors", 0)
                else:
                    batch_stats.added += getattr(source_stats, "added", 0)
                    batch_stats.updated += getattr(source_stats, "updated", 0)
                    batch_stats.skipped += getattr(source_stats, "skipped", 0)
                    batch_stats.errors += getattr(source_stats, "errors", 0)

            if progress and task is not None:
                progress.update(
                    task,
                    description=f"{source.title()}: {batch_stats.added} added, {batch_stats.updated} updated",
                )
                progress.advance(task)

    # Final commit
    conn.commit()
    print(
        f"\nExport results: added: {batch_stats.added}, updated: {batch_stats.updated}, skipped: {batch_stats.skipped}"
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
        print(f"  {row['source']}: {row['sessions']} sessions, {row['messages']} messages")

    conn.close()


@app.command()
def main(
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Output database path (default: from config)"),
    ] = None,
    # Source selection flags (mutually exclusive behavior handled in code)
    claude_only: Annotated[
        bool, typer.Option("--claude-only", help="Only export Claude Code")
    ] = False,
    kiro_only: Annotated[bool, typer.Option("--kiro-only", help="Only export Kiro CLI")] = False,
    gemini_only: Annotated[
        bool, typer.Option("--gemini-only", help="Only export Gemini CLI")
    ] = False,
    kilocode_only: Annotated[
        bool, typer.Option("--kilocode-only", help="Only export Kilocode CLI")
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
        typer.Option("--aider-paths", help="Additional paths to search for Aider history files"),
    ] = None,
    # Safety options
    dated: Annotated[
        bool, typer.Option("--dated", help="Append date suffix to output filename")
    ] = False,
    backup: Annotated[
        bool, typer.Option("--backup", help="Create backup of existing database before export")
    ] = False,
    # Export mode
    full: Annotated[
        bool, typer.Option("--full", help="Re-import all files, ignoring change detection")
    ] = False,
) -> None:
    """Export AI coding assistant sessions to SQLite database.

    Supported sources:
    - claude_code: Claude Code (~/.claude/projects/)
    - kiro_cli: Kiro CLI (~/Library/Application Support/kiro-cli/)
    - gemini_cli: Gemini CLI (~/.gemini/tmp/)
    - kilocode_cli: Kilocode CLI (~/.kilocode/cli/)
    - opencode: OpenCode CLI (~/.local/share/opencode/storage/)
    - repoprompt: RepoPrompt (~/Library/Application Support/RepoPrompt/)

    Examples:
        session-export                    # Export all sources
        session-export --claude-only      # Only Claude Code
        session-export --sources gemini opencode  # Specific sources
        session-export --dated --backup   # Dated output with backup
    """
    output_path = Path(output) if output else DEFAULT_DB
    if dated:
        output_path = output_path.with_stem(f"{output_path.stem}_{datetime.now():%Y-%m-%d}")

    if backup and output_path.exists():
        backup_path = output_path.with_suffix(f".backup{output_path.suffix}")
        shutil.copy2(output_path, backup_path)
        print(f"Created backup: {backup_path}")

    # Determine which sources to export
    only_flags = {
        "claude": claude_only,
        "kiro": kiro_only,
        "gemini": gemini_only,
        "kilocode": kilocode_only,
    }
    active = [k for k, v in only_flags.items() if v]
    if len(active) > 1:
        raise typer.BadParameter("Only one --*-only flag can be specified at a time")

    if active:
        export_sources = {active[0]}
    elif sources:
        invalid = set(sources) - set(SOURCE_CHOICES)
        if invalid:
            raise typer.BadParameter(f"Invalid sources: {invalid}. Valid choices: {SOURCE_CHOICES}")
        export_sources = set(sources)
    else:
        export_sources = set(SOURCE_CHOICES)

    incremental = not full
    _run_export(output_path, export_sources, incremental, aider_paths)


if __name__ == "__main__":
    app()
