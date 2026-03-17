"""studyctl update + upgrade CLI commands."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.table import Table

from studyctl.cli._doctor import _get_registry
from studyctl.cli._shared import console

if TYPE_CHECKING:
    from studyctl.doctor.models import CheckResult

# Components the user can target with --component
VALID_COMPONENTS = ("packages", "agents", "database", "voice", "all")

# Map doctor categories -> upgrade components
_CATEGORY_TO_COMPONENT: dict[str, str] = {
    "updates": "packages",
    "agents": "agents",
    "database": "database",
    "voice": "voice",
}

STATUS_ICONS = {
    "pass": "[green]\u2713[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]\u2717[/red]",
    "info": "[blue]i[/blue]",
}


# ---------------------------------------------------------------------------
# Helper: package manager detection
# ---------------------------------------------------------------------------


def _detect_package_manager() -> str:
    """Detect the package manager used to install studyctl.

    Probe order: uv -> brew -> pip (fallback).
    """
    # uv tool list includes studyctl if installed via uv tool install
    try:
        r = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and "studyctl" in r.stdout:
            return "uv"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # brew list --formula
    try:
        r = subprocess.run(
            ["brew", "list", "--formula"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and "studyctl" in r.stdout:
            return "brew"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return "pip"


# ---------------------------------------------------------------------------
# Helper: database backup + pruning
# ---------------------------------------------------------------------------


def _backup_database(db_path: Path, backup_dir: Path) -> Path | None:
    """Copy *db_path* into *backup_dir* with a timestamp suffix.

    Returns the backup path on success, or None if the source does not exist.
    """
    if not db_path.exists():
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.name}.bak.{stamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _prune_old_backups(backup_dir: Path, max_age_days: int = 30) -> None:
    """Remove backup files older than *max_age_days* from *backup_dir*."""
    if not backup_dir.exists():
        return
    cutoff = time.time() - (max_age_days * 86400)
    for f in backup_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helper: apply upgrades
# ---------------------------------------------------------------------------


def _upgrade_packages(manager: str, dry_run: bool) -> bool:
    """Run the package upgrade command for the detected manager.

    Returns True on success (or dry_run).
    """
    if manager == "uv":
        cmd = ["uv", "tool", "upgrade", "studyctl"]
    elif manager == "brew":
        cmd = ["brew", "upgrade", "studyctl"]
    else:
        cmd = ["pip", "install", "--upgrade", "studyctl"]

    if dry_run:
        console.print(f"  [dim]Would run: {' '.join(cmd)}[/dim]")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        console.print("[green]  Package upgrade succeeded.[/green]")
        return True
    console.print(f"[red]  Package upgrade failed:[/red] {result.stderr.strip()}")
    return False


def _upgrade_database(dry_run: bool) -> bool:
    """Back up the review database and run any pending migrations.

    Returns True on success (or dry_run).
    """
    from studyctl.settings import get_db_path

    db_path = get_db_path()
    backup_dir = Path("~/.config/studyctl/db-backups").expanduser()

    if dry_run:
        console.print(f"  [dim]Would back up {db_path} -> {backup_dir}/[/dim]")
        console.print("  [dim]Would run database migrations.[/dim]")
        return True

    backup = _backup_database(db_path, backup_dir)
    if backup:
        console.print(f"  [green]Database backed up to {backup}[/green]")
        _prune_old_backups(backup_dir)
    else:
        console.print("  [dim]No database to back up (not yet created).[/dim]")

    # Ensure schema is current (idempotent)
    try:
        from studyctl.review_db import ensure_tables

        ensure_tables(db_path)
        console.print("  [green]Database schema is current.[/green]")
    except Exception as exc:
        console.print(f"  [red]Database migration failed:[/red] {exc}")
        return False

    return True


def _result_matches_component(result: CheckResult, component: str) -> bool:
    """Return True if *result* is relevant to the upgrade *component*."""
    if component == "all":
        return True
    mapped = _CATEGORY_TO_COMPONENT.get(result.category)
    return mapped == component


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@click.command("update")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
@click.pass_context
def update(ctx: click.Context, as_json: bool) -> None:
    """Check for available updates (informational only, always exits 0)."""
    registry = _get_registry()
    results = registry.run_all()

    # Filter to update-relevant results only (updates + core for version info)
    update_results = [r for r in results if r.category in ("updates", "core")]

    if as_json:
        click.echo(json.dumps([r.to_dict() for r in update_results], indent=2))
        ctx.exit(0)
        return

    has_updates = any(r.status == "warn" and r.category == "updates" for r in update_results)

    table = Table(title="studyctl update check", show_lines=False)
    table.add_column("Status", justify="center", width=3)
    table.add_column("Check", style="cyan")
    table.add_column("Details")
    table.add_column("Action", style="dim")

    for r in update_results:
        icon = STATUS_ICONS.get(r.status, "?")
        table.add_row(icon, r.name, r.message, r.fix_hint or "")

    console.print(table)

    if has_updates:
        console.print(
            "\n[yellow]Updates available.[/yellow] Run [bold]studyctl upgrade[/bold] to apply."
        )
    else:
        console.print("\n[green]Everything is up to date.[/green]")

    ctx.exit(0)


@click.command("upgrade")
@click.option("--dry-run", is_flag=True, help="Show what would be done without applying changes")
@click.option(
    "--component",
    type=click.Choice(VALID_COMPONENTS),
    default="all",
    show_default=True,
    help="Upgrade a specific component only",
)
@click.option("--force", is_flag=True, help="Skip confirmation prompts")
@click.pass_context
def upgrade(ctx: click.Context, dry_run: bool, component: str, force: bool) -> None:
    """Apply available updates (packages, database migrations, agent definitions)."""
    registry = _get_registry()
    results = registry.run_all()

    # Find results that need action and match the requested component
    actionable = [
        r
        for r in results
        if r.status in ("warn", "fail") and r.fix_auto and _result_matches_component(r, component)
    ]

    if not actionable:
        console.print("[green]Everything is up to date.[/green]")
        ctx.exit(0)
        return

    if dry_run:
        console.print("[bold cyan]Dry run[/bold cyan] — no changes will be made.\n")
        console.print("The following would be upgraded:")
        for r in actionable:
            console.print(f"  [yellow]![/yellow] {r.name}: {r.message}")
            mapped = _CATEGORY_TO_COMPONENT.get(r.category, r.category)
            if mapped == "packages":
                manager = _detect_package_manager()
                _upgrade_packages(manager, dry_run=True)
            elif mapped == "database":
                _upgrade_database(dry_run=True)
        ctx.exit(0)
        return

    # Non-dry-run: apply upgrades grouped by component
    needs_packages = any(_CATEGORY_TO_COMPONENT.get(r.category) == "packages" for r in actionable)
    needs_database = any(_CATEGORY_TO_COMPONENT.get(r.category) == "database" for r in actionable)

    success = True

    if needs_packages:
        console.print("[bold]Upgrading packages...[/bold]")
        manager = _detect_package_manager()
        if not _upgrade_packages(manager, dry_run=False):
            success = False

    if needs_database:
        console.print("[bold]Upgrading database...[/bold]")
        if not _upgrade_database(dry_run=False):
            success = False

    if success:
        console.print("\n[green]Upgrade complete.[/green]")
    else:
        console.print("\n[red]Upgrade completed with errors.[/red] Check output above.")

    ctx.exit(0 if success else 1)
