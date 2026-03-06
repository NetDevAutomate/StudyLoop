#!/usr/bin/env python3
"""Sync sessions.db between machines.

Streams SQL deltas over SSH instead of copying entire database files.
Only new sessions and messages are transferred using INSERT OR IGNORE.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import subprocess
from datetime import datetime
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

# Tables to sync (order matters — sessions before messages for FK)
SYNC_TABLES = ["sessions", "messages", "session_notes", "session_tags"]

# Create Typer app
app = typer.Typer(
    name="session-sync",
    help="Sync sessions.db between machines.",
    add_completion=True,
    rich_markup_mode="rich",
)

console = Console()

# Load configuration
config = load_config()
DB_PATH = get_db_path(config)

# Setup logging
log_path = get_log_path(config)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# SSH multiplexing options — reuse connections to avoid port exhaustion
_SSH_MUX_DIR = Path("/tmp/session-sync-ssh")
_SSH_MUX_OPTS = [
    "-o",
    "ControlMaster=auto",
    "-o",
    f"ControlPath={_SSH_MUX_DIR}/%r@%h:%p",
    "-o",
    "ControlPersist=30",
]


def _ensure_mux_dir() -> None:
    _SSH_MUX_DIR.mkdir(mode=0o700, exist_ok=True)


def _resolve_remote(remote: str) -> tuple[str, str]:
    """Resolve a remote target to (user@host, db_path).

    Accepts either:
    - An endpoint name from config (e.g. "macmini")
    - A full remote path (e.g. "user@host:/path/to/db")
    """
    # Check if it's a configured endpoint name
    endpoints = get_endpoints(config)
    if remote in endpoints:
        ep = endpoints[remote]
        username = ep["username"]
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
                    ["ssh", *_SSH_MUX_OPTS, "-o", "ConnectTimeout=3", host, "true"],
                    capture_output=True,
                    timeout=5,
                )
                console.print(f"[dim]Resolved endpoint '{remote}' → {host}:{path}[/dim]")
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


def _remote_sql(host: str, db_path: str, query: str) -> str:
    """Execute a SQL query on the remote DB via SSH and return stdout."""
    _ensure_mux_dir()
    result = subprocess.run(
        ["ssh", *_SSH_MUX_OPTS, host, f'sqlite3 {db_path} "{query}"'],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Remote SQL failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _get_session_ids(db_path_or_host: Path | str, remote_db: str | None = None) -> set[str]:
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


def _get_sync_state(local_db: Path, host: str, remote_db: str) -> tuple[set[str], set[str]]:
    """Calculate new + updated session IDs by comparing updated_at timestamps.

    Returns (new_ids, updated_ids).
    """
    # Get local sessions with timestamps
    conn = sqlite3.connect(local_db)
    local_sessions = {
        r[0]: r[1] for r in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
    }
    conn.close()

    # Get remote sessions with timestamps (pipe-delimited)
    raw = _remote_sql(host, remote_db, "SELECT id || '|' || COALESCE(updated_at,'') FROM sessions")
    remote_sessions = {}
    for line in raw.splitlines():
        if "|" in line:
            sid, ts = line.split("|", 1)
            remote_sessions[sid] = ts
        elif line:
            remote_sessions[line] = ""

    new_ids = set(local_sessions) - set(remote_sessions)
    updated_ids = set()
    for sid in set(local_sessions) & set(remote_sessions):
        local_ts = local_sessions[sid] or ""
        remote_ts = remote_sessions[sid] or ""
        if local_ts > remote_ts:
            updated_ids.add(sid)

    return new_ids, updated_ids


def _dump_delta_sql(db_path: Path, session_ids: set[str]) -> str:
    """Generate INSERT OR REPLACE SQL for the given session IDs.

    Uses sqlite3 .mode insert for proper quoting, then transforms to
    INSERT OR REPLACE so both new and updated rows are handled.
    """
    if not session_ids:
        return ""

    placeholders = ",".join(f"'{sid}'" for sid in session_ids)
    commands = [
        ".mode insert sessions",
        f"SELECT * FROM sessions WHERE id IN ({placeholders});",
        ".mode insert messages",
        f"SELECT * FROM messages WHERE session_id IN ({placeholders});",
    ]
    for table in ["session_notes", "session_tags"]:
        commands.append(f".mode insert {table}")
        commands.append(f"SELECT * FROM {table} WHERE session_id IN ({placeholders});")

    result = subprocess.run(
        ["sqlite3", str(db_path)],
        input="\n".join(commands),
        capture_output=True,
        text=True,
    )
    # Ignore errors from missing optional tables (session_notes, session_tags)
    sql = result.stdout.replace("INSERT INTO", "INSERT OR REPLACE INTO")
    return sql


def _stream_sql_to_target(sql: str, target: Path | tuple[str, str]) -> bool:
    """Stream SQL into a local DB or remote DB over SSH.

    target is either a local Path or (host, db_path) tuple.
    """
    if not sql.strip():
        return True

    # Append FTS rebuild
    sql += "\nINSERT INTO messages_fts(messages_fts) VALUES('rebuild');\n"

    if isinstance(target, Path):
        result = subprocess.run(
            ["sqlite3", str(target)],
            input=sql,
            capture_output=True,
            text=True,
        )
    else:
        host, db_path = target
        result = subprocess.run(
            ["ssh", *_SSH_MUX_OPTS, "-C", host, f"sqlite3 {db_path}"],
            input=sql,
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Filter out warnings about missing optional tables
        errors = [
            line for line in stderr.splitlines() if "Error" in line and "no such table" not in line
        ]
        if errors:
            logger.error(f"SQL import errors: {chr(10).join(errors)}")
            return False
    return True


def create_backup(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = get_backup_dir(config)
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{db_path.stem}_backup_{timestamp}.db"
    shutil.copy2(db_path, backup_path)

    logger.info(f"Backup created: {backup_path}")
    console.print(f"[green]✅ Backup created:[/green] {backup_path}")
    return backup_path


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


@app.command()
def pull(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[Path | None, typer.Option("--db", "-d", help="Local database path")] = None,
    no_backup: Annotated[bool, typer.Option("--no-backup", help="Skip backup")] = False,
) -> None:
    """Pull new sessions from remote via SQL streaming."""
    local_db = db or DB_PATH
    host, remote_db = _resolve_remote(remote)

    console.print(f"[bold]Pulling from:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")
    console.print()

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    if not no_backup:
        create_backup(local_db)

    show_db_stats(local_db, "Local (before)")

    # Calculate delta: what does remote have that's new or newer?
    console.print("\n[bold]Calculating delta...[/bold]")
    # Reverse: remote is "local" from the perspective of what to pull
    # We need remote's updated_at vs our updated_at
    # Reuse _get_sync_state but swap: get remote sessions newer than ours
    raw = _remote_sql(host, remote_db, "SELECT id || '|' || COALESCE(updated_at,'') FROM sessions")
    remote_sessions = {}
    for line in raw.splitlines():
        if "|" in line:
            sid, ts = line.split("|", 1)
            remote_sessions[sid] = ts
        elif line:
            remote_sessions[line] = ""

    conn = sqlite3.connect(local_db)
    local_sessions = {
        r[0]: r[1] or "" for r in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
    }
    conn.close()

    new_ids = set(remote_sessions) - set(local_sessions)
    updated_ids = {
        sid
        for sid in set(remote_sessions) & set(local_sessions)
        if remote_sessions[sid] > local_sessions[sid]
    }
    all_ids = new_ids | updated_ids

    if not all_ids:
        console.print("[green]✅ Already up to date[/green]")
        return

    console.print(f"  New: [cyan]{len(new_ids)}[/cyan], Updated: [cyan]{len(updated_ids)}[/cyan]")

    # Dump from remote
    placeholders = ",".join(f"'{sid}'" for sid in all_ids)
    commands = []
    for table in SYNC_TABLES:
        commands.append(f".mode insert {table}")
        id_col = "id" if table == "sessions" else "session_id"
        commands.append(f"SELECT * FROM {table} WHERE {id_col} IN ({placeholders});")

    result = subprocess.run(
        ["ssh", *_SSH_MUX_OPTS, "-C", host, f"sqlite3 {remote_db}"],
        input="\n".join(commands),
        capture_output=True,
        text=True,
    )
    sql = result.stdout.replace("INSERT INTO", "INSERT OR REPLACE INTO")

    console.print("[bold]Importing...[/bold]")
    if not _stream_sql_to_target(sql, local_db):
        console.print("[red]❌ Failed to import[/red]")
        raise typer.Exit(1)

    console.print(f"\n[green]✅ Pulled {len(new_ids)} new, {len(updated_ids)} updated[/green]")
    show_db_stats(local_db, "Local (after)")


@app.command()
def push(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[Path | None, typer.Option("--db", "-d", help="Local database path")] = None,
) -> None:
    """Push new and updated sessions to remote via SQL streaming."""
    local_db = db or DB_PATH
    host, remote_db = _resolve_remote(remote)

    console.print(f"[bold]Pushing to:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    show_db_stats(local_db, "Local")

    console.print("\n[bold]Calculating delta...[/bold]")
    new_ids, updated_ids = _get_sync_state(local_db, host, remote_db)
    all_ids = new_ids | updated_ids

    if not all_ids:
        console.print("[green]✅ Already up to date[/green]")
        return

    console.print(f"  New: [cyan]{len(new_ids)}[/cyan], Updated: [cyan]{len(updated_ids)}[/cyan]")

    sql = _dump_delta_sql(local_db, all_ids)

    console.print("[bold]Streaming to remote...[/bold]")
    if _stream_sql_to_target(sql, (host, remote_db)):
        console.print(f"[green]✅ Pushed {len(new_ids)} new, {len(updated_ids)} updated[/green]")
    else:
        console.print("[red]❌ Failed to push to remote[/red]")
        raise typer.Exit(1)


@app.command()
def sync(
    remote: Annotated[str, typer.Argument(help="Remote path (user@host:path)")],
    db: Annotated[Path | None, typer.Option("--db", "-d", help="Local database path")] = None,
    no_backup: Annotated[bool, typer.Option("--no-backup", help="Skip backup")] = False,
) -> None:
    """Two-way sync: stream deltas in both directions.

    Both machines end up with the same data.
    """
    local_db = db or DB_PATH
    host, remote_db = _resolve_remote(remote)

    console.print(f"[bold]Syncing with:[/bold] {remote}")
    console.print(f"[bold]Local DB:[/bold] {local_db}")
    console.print()

    if not local_db.exists():
        console.print(f"[red]❌ Local database not found: {local_db}[/red]")
        raise typer.Exit(1)

    if not no_backup:
        create_backup(local_db)

    # Calculate deltas in both directions using one SSH call for remote state
    console.print("[bold]Calculating deltas...[/bold]")
    raw = _remote_sql(host, remote_db, "SELECT id || '|' || COALESCE(updated_at,'') FROM sessions")
    remote_sessions = {}
    for line in raw.splitlines():
        if "|" in line:
            sid, ts = line.split("|", 1)
            remote_sessions[sid] = ts
        elif line:
            remote_sessions[line] = ""

    conn = sqlite3.connect(local_db)
    local_sessions = {
        r[0]: r[1] or "" for r in conn.execute("SELECT id, updated_at FROM sessions").fetchall()
    }
    conn.close()

    # Push: local new + local newer
    push_new = set(local_sessions) - set(remote_sessions)
    push_updated = {
        sid
        for sid in set(local_sessions) & set(remote_sessions)
        if local_sessions[sid] > remote_sessions[sid]
    }
    # Pull: remote new + remote newer
    pull_new = set(remote_sessions) - set(local_sessions)
    pull_updated = {
        sid
        for sid in set(local_sessions) & set(remote_sessions)
        if remote_sessions[sid] > local_sessions[sid]
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
        placeholders = ",".join(f"'{sid}'" for sid in pull_ids)
        commands = []
        for table in SYNC_TABLES:
            id_col = "id" if table == "sessions" else "session_id"
            commands.append(f".mode insert {table}")
            commands.append(f"SELECT * FROM {table} WHERE {id_col} IN ({placeholders});")

        result = subprocess.run(
            ["ssh", *_SSH_MUX_OPTS, "-C", host, f"sqlite3 {remote_db}"],
            input="\n".join(commands),
            capture_output=True,
            text=True,
        )
        sql = result.stdout.replace("INSERT INTO", "INSERT OR REPLACE INTO")
        if sql.strip() and not _stream_sql_to_target(sql, local_db):
            console.print("[red]❌ Failed to pull[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Pulled {len(pull_new)} new, {len(pull_updated)} updated[/green]")
    else:
        console.print("\n[bold]Step 1:[/bold] Nothing to pull")

    # Step 2: Push local → remote
    push_ids = push_new | push_updated
    if push_ids:
        console.print(f"\n[bold]Step 2: Pushing {len(push_ids)} sessions...[/bold]")
        sql = _dump_delta_sql(local_db, push_ids)
        if sql.strip() and not _stream_sql_to_target(sql, (host, remote_db)):
            console.print("[red]❌ Failed to push[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Pushed {len(push_new)} new, {len(push_updated)} updated[/green]")
    else:
        console.print("\n[bold]Step 2:[/bold] Nothing to push")

    if not pull_ids and not push_ids:
        console.print("\n[green]✅ Already in sync[/green]")
    else:
        console.print("\n[green]✅ Sync complete![/green]")
    show_db_stats(local_db, "Final")


@app.command()
def status(
    db: Annotated[Path | None, typer.Option("--db", "-d", help="Database path")] = None,
) -> None:
    """Show local database status and sync info."""
    local_db = db or DB_PATH

    if not local_db.exists():
        console.print(f"[red]❌ Database not found: {local_db}[/red]")
        raise typer.Exit(1)

    show_db_stats(local_db, "Local Database")

    # Show recent backups
    backup_dir = get_backup_dir(config)
    if backup_dir.exists():
        backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if backups:
            console.print(f"\n[bold]Recent backups:[/bold] ({backup_dir})")
            for backup in backups[:5]:
                mtime = datetime.fromtimestamp(backup.stat().st_mtime)
                size_mb = backup.stat().st_size / 1024 / 1024
                console.print(f"  {backup.name} ({size_mb:.1f} MB) - {mtime:%Y-%m-%d %H:%M}")


@app.command()
def endpoints() -> None:
    """List configured sync endpoints."""
    eps = get_endpoints(config)
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


def main() -> None:
    """Entry point for session-sync CLI."""
    app()


if __name__ == "__main__":
    main()
