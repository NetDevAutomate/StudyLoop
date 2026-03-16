"""Config commands — configuration management."""

from __future__ import annotations

import click
from rich.table import Table

from studyctl.cli._shared import console, offer_agent_install
from studyctl.shared import init_interactive_config


@click.group(name="config")
def config_group() -> None:
    """Manage studyctl configuration."""


@config_group.command(name="init")
@click.option(
    "--install-agents/--no-install-agents",
    default=None,
    help="Install AI agent definitions after config (auto-detects available tools).",
)
def config_init(install_agents: bool | None) -> None:
    """Interactive setup — configure knowledge bridging, NotebookLM, and Obsidian integration."""
    path = init_interactive_config(console)
    console.print(f"\n[bold green]\u2713 Configuration saved to {path}[/bold green]")

    # Offer to install agents
    offer_agent_install(install_agents)

    console.print("\nNext steps:")
    console.print("  1. Add study topics:  studyctl topics")
    console.print("  2. Start a session:   /agent socratic-mentor  (Claude Code)")
    console.print("                        kiro-cli chat --agent study-mentor  (Kiro)")


@config_group.command(name="show")
def config_show() -> None:
    """Display current configuration."""
    from studyctl.settings import _CONFIG_PATH, load_settings

    settings = load_settings()
    config_path = _CONFIG_PATH

    if not config_path.exists():
        console.print("[red]No config file found.[/red] Run: studyctl config init")
        return

    console.print(f"[bold]Configuration[/bold] \u2014 {config_path}\n")

    # Core settings
    table = Table(title="Core Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_column("Status", justify="center")

    # Obsidian
    obsidian_path = settings.obsidian_base
    obsidian_exists = obsidian_path.exists()
    table.add_row(
        "Obsidian vault",
        str(obsidian_path),
        "[green]\u2713[/green]" if obsidian_exists else "[red]\u2717[/red]",
    )

    # Session DB
    db_exists = settings.session_db.exists()
    table.add_row(
        "Session database",
        str(settings.session_db),
        "[green]\u2713[/green]" if db_exists else "[dim]\u2014[/dim]",
    )

    # State dir
    state_exists = settings.state_dir.exists()
    table.add_row(
        "State directory",
        str(settings.state_dir),
        "[green]\u2713[/green]" if state_exists else "[dim]\u2014[/dim]",
    )

    # Knowledge domains
    kd = settings.knowledge_domains
    if kd.primary:
        table.add_row("Knowledge bridging", f"Primary: {kd.primary}", "[green]\u2713[/green]")
    else:
        table.add_row("Knowledge bridging", "Not configured", "[dim]\u2014[/dim]")

    # NotebookLM
    nlm_enabled = settings.notebooklm.enabled
    table.add_row(
        "NotebookLM",
        "Enabled" if nlm_enabled else "Disabled",
        "[green]\u2713[/green]" if nlm_enabled else "[dim]\u2014[/dim]",
    )

    # Sync
    if settings.sync_remote:
        table.add_row("Sync remote", settings.sync_remote, "[green]\u2713[/green]")
    else:
        table.add_row("Sync remote", "Not configured", "[dim]\u2014[/dim]")

    console.print(table)

    # Topics
    if settings.topics:
        topics_table = Table(title="\nStudy Topics")
        topics_table.add_column("Name", style="bold")
        topics_table.add_column("Slug", style="dim")
        topics_table.add_column("Path")
        topics_table.add_column("Notebook", style="dim")
        topics_table.add_column("Tags")

        for t in settings.topics:
            path_str = str(t.obsidian_path)
            path_str = (
                f"[green]{path_str}[/green]"
                if t.obsidian_path.exists()
                else f"[red]{path_str}[/red]"
            )

            nb = t.notebook_id[:12] + "\u2026" if t.notebook_id else "[dim]\u2014[/dim]"
            tags = ", ".join(t.tags) if t.tags else "[dim]\u2014[/dim]"
            topics_table.add_row(t.name, t.slug, path_str, nb, tags)

        console.print(topics_table)
    else:
        console.print("\n[dim]No topics configured. Add topics to config.yaml.[/dim]")
