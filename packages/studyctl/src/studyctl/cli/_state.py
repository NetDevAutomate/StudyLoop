"""State commands — cross-machine state sync."""

from __future__ import annotations

import click

from studyctl.cli._shared import console
from studyctl.shared import init_config, pull_state, push_state
from studyctl.shared import sync_status as shared_sync_status


@click.group(name="state")
def state_group() -> None:
    """Cross-machine state sync (via Obsidian vault)."""


@state_group.command(name="push")
@click.argument("remote", required=False)
def state_push(remote: str | None) -> None:
    """Push local progress and sync state to remote machine(s)."""
    try:
        pushed = push_state(remote)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("Run 'studyctl state init' first")
        raise SystemExit(1) from None
    if pushed:
        for f in pushed:
            console.print(f"[green]\u2713[/green] {f}")
    else:
        console.print("[dim]Everything up to date (or no remotes reachable)[/dim]")


@state_group.command(name="pull")
@click.argument("remote", required=False)
def state_pull(remote: str | None) -> None:
    """Pull progress and sync state from remote machine(s)."""
    try:
        pulled = pull_state(remote)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from None
    if pulled:
        for f in pulled:
            console.print(f"[green]\u2713[/green] {f}")
    else:
        console.print("[dim]Everything up to date (or no remotes reachable)[/dim]")


@state_group.command(name="status")
def state_status_cmd() -> None:
    """Check sync config and remote connectivity."""
    info = shared_sync_status()
    if not info["configured"]:
        console.print("[red]Not configured.[/red] Run: studyctl state init")
        console.print(f"Config: {info['config_path']}")
        return
    console.print(f"Local machine: [bold]{info['local']}[/bold]")
    for name, r in info["remotes"].items():
        status = "[green]reachable[/green]" if r["reachable"] else "[red]unreachable[/red]"
        console.print(f"  {name} ({r['host']}): {status}")


@state_group.command(name="init")
def state_init() -> None:
    """Create default sync config."""
    path = init_config()
    console.print(f"[green]\u2713[/green] Config at {path}")
    console.print("Edit remotes to match your machines, then run 'studyctl state status'")
