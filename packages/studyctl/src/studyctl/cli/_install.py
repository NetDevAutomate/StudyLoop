"""Typed install commands for tools and agent definitions."""

from __future__ import annotations

from pathlib import Path

import click

from studyctl.cli._shared import console
from studyctl.installers import (
    InstallError,
    install_agent_definitions,
    install_workspace_tools,
    require_repo_root,
)


@click.group(name="install")
def install_group() -> None:
    """Install studyctl tools and agent definitions."""


@install_group.command(name="tools")
@click.option(
    "--repo-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Repository root to install from (defaults to auto-detect).",
)
@click.option("--sync/--skip-sync", default=True, show_default=True, help="Run `uv sync` first.")
@click.option(
    "--force/--no-force",
    default=True,
    show_default=True,
    help="Force reinstall uv tools.",
)
def install_tools(repo_root: Path | None, sync: bool, force: bool) -> None:
    """Install editable workspace packages as uv tools."""
    try:
        root = require_repo_root(repo_root)
        installed = install_workspace_tools(root, sync_workspace=sync, force=force)
    except InstallError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(f"Tool installation failed: {exc}") from exc

    console.print("[green]Installed tools:[/green] " + ", ".join(installed))


@install_group.command(name="agents")
@click.option(
    "--repo-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Repository root to install from (defaults to auto-detect).",
)
@click.option(
    "--tool",
    "tools",
    multiple=True,
    type=click.Choice(["kiro", "claude", "gemini", "opencode", "codex", "amp"]),
    help="Install for a specific AI tool. Repeat to install multiple.",
)
@click.option("--uninstall", is_flag=True, help="Remove installed agent definitions instead.")
def install_agents(repo_root: Path | None, tools: tuple[str, ...], uninstall: bool) -> None:
    """Install or remove agent definitions for supported AI tools."""
    try:
        root = require_repo_root(repo_root)
        summary = install_agent_definitions(root, tools=list(tools) or None, uninstall=uninstall)
    except InstallError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        action = "Agent uninstall" if uninstall else "Agent install"
        raise click.ClickException(f"{action} failed: {exc}") from exc

    action_word = "Removed" if uninstall else "Updated"
    lines = [f"{name}: {count}" for name, count in summary.items()]
    console.print(f"[green]{action_word} agent definitions.[/green]")
    for line in lines:
        console.print(f"  {line}")
