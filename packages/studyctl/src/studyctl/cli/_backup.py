"""Backup and restore commands for studyctl user data.

Backs up sessions.db, review.db, and config.yaml to a timestamped
directory under ~/.config/studyctl/backups/. Restore reverses the
process with a safety backup of the current state first.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.cli._shared import console
from studyctl.settings import _CONFIG_PATH, CONFIG_DIR, DEFAULT_DB


def _get_backup_dir() -> Path:
    return CONFIG_DIR / "backups"


def _get_assets() -> list[tuple[str, Path]]:
    """Return list of (label, path) for all backable assets."""
    review_db = CONFIG_DIR / "review.db"
    return [
        ("sessions.db", DEFAULT_DB),
        ("review.db", review_db),
        ("config.yaml", _CONFIG_PATH),
    ]


def _create_backup(tag: str | None = None) -> Path | None:
    """Create a timestamped backup of all user data.

    Returns the backup directory path, or None if nothing to back up.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"backup_{timestamp}" if not tag else f"backup_{tag}_{timestamp}"
    backup_dir = _get_backup_dir() / name
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for label, path in _get_assets():
        if path.exists():
            shutil.copy2(path, backup_dir / label)
            copied += 1

    if copied == 0:
        backup_dir.rmdir()
        return None

    return backup_dir


@click.command()
@click.option("--tag", "-t", default=None, help="Optional tag for the backup name.")
def backup(tag: str | None) -> None:
    """Back up sessions database, review database, and config.

    Creates a timestamped snapshot under ~/.config/studyctl/backups/.
    Use before upgrades or risky changes.
    """
    assets = _get_assets()
    existing = [(label, p) for label, p in assets if p.exists()]

    if not existing:
        console.print("[yellow]Nothing to back up — no databases or config found.[/yellow]")
        return

    console.print("[bold]Creating backup...[/bold]")
    for label, p in existing:
        size_kb = p.stat().st_size / 1024
        console.print(f"  {label}: {size_kb:.0f} KB")

    result = _create_backup(tag)
    if result:
        console.print(f"\n[green]Backup saved:[/green] {result}")
    else:
        console.print("[yellow]No files to back up.[/yellow]")


@click.command()
@click.argument("backup_name", required=False)
@click.option("--confirm", is_flag=True, help="Required to actually restore.")
def restore(backup_name: str | None, confirm: bool) -> None:
    """Restore from a previous backup.

    With no argument, lists available backups.
    With a backup name, restores that backup (requires --confirm).
    """
    backup_dir = _get_backup_dir()

    if not backup_dir.exists() or not any(backup_dir.iterdir()):
        console.print("[yellow]No backups found.[/yellow]")
        console.print("  Run [bold]studyctl backup[/bold] to create one.")
        return

    # List mode
    if backup_name is None:
        console.print("[bold]Available backups:[/bold]\n")
        for d in sorted(backup_dir.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("backup_"):
                files = list(d.iterdir())
                total_kb = sum(f.stat().st_size for f in files) / 1024
                file_list = ", ".join(f.name for f in sorted(files))
                console.print(f"  [cyan]{d.name}[/cyan]  ({total_kb:.0f} KB)  \\[{file_list}]")
        console.print("\n  Restore: [bold]studyctl restore <name> --confirm[/bold]")
        return

    # Find the backup
    target = backup_dir / backup_name
    if not target.exists() or not target.is_dir():
        console.print(f"[red]Backup not found:[/red] {backup_name}")
        console.print("  Run [bold]studyctl restore[/bold] to list available backups.")
        return

    # Show what will be restored
    console.print(f"[bold]Restoring from:[/bold] {backup_name}\n")
    for f in sorted(target.iterdir()):
        size_kb = f.stat().st_size / 1024
        console.print(f"  {f.name}: {size_kb:.0f} KB")

    if not confirm:
        console.print("\n[yellow]Dry run.[/yellow] Add [bold]--confirm[/bold] to actually restore.")
        return

    # Safety backup of current state before overwriting
    console.print("\n[dim]Creating safety backup of current state...[/dim]")
    safety = _create_backup(tag="pre-restore")
    if safety:
        console.print(f"  Safety backup: {safety.name}")

    # Restore each file
    asset_map = dict(_get_assets())
    restored = 0
    for f in target.iterdir():
        dest = asset_map.get(f.name)
        if dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            console.print(f"  [green]Restored:[/green] {f.name}")
            restored += 1

    if restored:
        console.print(f"\n[green]Restore complete.[/green] {restored} file(s) restored.")
        console.print("  Run [bold]studyctl doctor[/bold] to verify.")
    else:
        console.print("[yellow]No matching files found in backup.[/yellow]")
