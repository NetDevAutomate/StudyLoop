"""Config commands — configuration management."""

from __future__ import annotations

import click
from rich.table import Table

from studyloop.cli._shared import console, offer_agent_install


def _stdin_is_interactive() -> bool:
    """Return whether a human terminal, rather than a pipe/agent, owns input."""
    import sys

    return sys.stdin.isatty()


@click.group(name="config")
def config_group() -> None:
    """Manage studyloop configuration."""


@config_group.command(name="init")
@click.option(
    "--install-agents/--no-install-agents",
    default=None,
    help="Explicitly install agent definitions after setup; omitted means no extra prompt.",
)
@click.pass_context
def config_init(ctx: click.Context, install_agents: bool | None) -> None:
    """Deprecated alias for studyloop setup."""
    from studyloop.cli._setup import setup as setup_command

    console.print(
        "[yellow]studyloop config init is a deprecated alias; using studyloop setup.[/yellow]"
    )
    ctx.invoke(
        setup_command,
        planning_base_url="",
        planning_model="",
        planning_api_key_ref="",
    )
    if install_agents is True:
        offer_agent_install(True)


@config_group.command(name="show")
def config_show() -> None:
    """Display current configuration."""
    from studyloop.settings import get_config_path, load_raw_config, load_settings

    settings = load_settings()
    config_path = get_config_path()

    if not config_path.exists():
        console.print("[red]No config file found.[/red] Run: studyloop setup")
        return

    raw = load_raw_config()

    console.print(f"[bold]Configuration[/bold] \u2014 {config_path}\n")

    # Core settings
    table = Table(title="Core Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_column("Status", justify="center")

    # Optional notes. Do not display Settings.obsidian_base's compatibility
    # default unless the legacy key is actually present in the user's config.
    raw_notes = raw.get("notes_path") or raw.get("obsidian_base")
    if raw_notes:
        notes_path = settings.notes_path or settings.obsidian_base
        notes_exists = notes_path.exists()
        label = "Notes folder" if raw.get("notes_path") else "Notes folder (legacy Obsidian)"
        table.add_row(
            label,
            str(notes_path),
            "[green]\u2713[/green]" if notes_exists else "[red]\u2717[/red]",
        )
    else:
        table.add_row("Notes folder", "Not configured", "[dim]\u2014[/dim]")

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


@config_group.command(name="lan-password")
def config_lan_password() -> None:
    """Set persistent LAN authentication without storing plaintext."""
    if not _stdin_is_interactive():
        raise click.ClickException(
            "LAN password setup requires an interactive terminal; piped or agent input is refused."
        )

    import getpass
    import hmac

    from studyloop.learner_credentials import hash_password
    from studyloop.settings import load_raw_config, write_raw_config

    try:
        password = getpass.getpass("New LAN password: ")
        if not password:
            raise click.ClickException("LAN password must not be empty")
        confirmation = getpass.getpass("Confirm LAN password: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise click.ClickException("LAN password setup cancelled; config was not changed") from exc
    if not hmac.compare_digest(password, confirmation):
        raise click.ClickException("LAN passwords did not match; config was not changed")

    raw = load_raw_config()
    raw.pop("lan_password", None)
    raw["lan_password_verifier"] = hash_password(password)
    password = ""
    confirmation = ""
    path = write_raw_config(raw)
    console.print(f"[green]LAN password verifier saved securely to {path}[/green]")
