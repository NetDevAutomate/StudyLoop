"""Setup wizard — first-run configuration for studyctl.

Guides users through the essential configuration questions one at a time.
Designed to be AuDHD-friendly: clear steps, no overwhelming walls of text,
sensible defaults so pressing Enter always works.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

import click
import yaml

from studyctl.cli._shared import console
from studyctl.settings import CONFIG_DIR


def _validate_path(value: str) -> Path:
    """Expand user and return a Path; raise UsageError if obviously invalid."""
    p = Path(value).expanduser()
    return p


@click.command(name="setup")
def setup() -> None:
    """First-run setup wizard — configure studyctl in under 2 minutes."""

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------
    console.print()
    console.print("[bold cyan]studyctl setup[/bold cyan]")
    console.print(
        "studyctl is your AuDHD study pipeline: it syncs Obsidian notes to "
        "NotebookLM, tracks spaced-repetition reviews, and schedules focused "
        "study sessions.\n"
    )
    console.print("[dim]Press Enter to accept the default shown in brackets.[/dim]\n")

    config: dict = {}

    # ------------------------------------------------------------------
    # Step 1 — Study materials directory
    # ------------------------------------------------------------------
    console.print("[bold]Step 1 of 5[/bold]  Where do you store course materials (PDFs, slides)?")
    materials_raw = click.prompt(
        "Study materials path",
        default="~/study-materials",
    )
    materials_path = _validate_path(materials_raw)
    config["content"] = {"base_path": str(materials_raw)}
    console.print(f"  [dim]Will use: {materials_path}[/dim]\n")

    # ------------------------------------------------------------------
    # Step 2 — AI coding assistant / MCP registration
    # ------------------------------------------------------------------
    console.print("[bold]Step 2 of 5[/bold]  Do you use an AI coding assistant?")
    console.print("  [dim](Claude Code, Kiro, Gemini CLI, etc.)[/dim]")
    has_ai = click.confirm("  Use an AI assistant?", default=True)
    if has_ai:
        assistant = click.prompt(
            "  Which one",
            default="claude-code",
            type=click.Choice(
                ["claude-code", "kiro", "gemini-cli", "other"],
                case_sensitive=False,
            ),
            show_choices=True,
        )
        config["ai_assistant"] = assistant
        console.print(
            f"  [dim]Noted. Run 'studyctl config init' to install agent definitions "
            f"for {assistant}.[/dim]\n"
        )
    else:
        console.print("  [dim]No problem — studyctl works fine as a standalone CLI.[/dim]\n")

    # ------------------------------------------------------------------
    # Step 3 — NotebookLM
    # ------------------------------------------------------------------
    console.print("[bold]Step 3 of 5[/bold]  Do you use Google NotebookLM?")
    console.print("  [dim](Optional — enables audio overview generation from your notes)[/dim]")
    use_nlm = click.confirm("  Enable NotebookLM integration?", default=False)
    config["notebooklm"] = {"enabled": use_nlm}
    if use_nlm:
        console.print(
            "  [dim]NotebookLM enabled. You'll need a Google account"
            " with NotebookLM access.[/dim]\n"
        )
    else:
        console.print("  [dim]Skipped — you can enable this later in config.yaml.[/dim]\n")

    # ------------------------------------------------------------------
    # Step 4 — Obsidian vault
    # ------------------------------------------------------------------
    console.print("[bold]Step 4 of 5[/bold]  Where is your Obsidian vault?")
    console.print("  [dim](Optional — enables note sync and spaced repetition)[/dim]")
    use_obsidian = click.confirm("  Configure Obsidian integration?", default=True)
    if use_obsidian:
        obsidian_raw = click.prompt("  Obsidian vault path", default="~/Obsidian")
        obsidian_path = _validate_path(obsidian_raw)
        config["obsidian_base"] = str(obsidian_raw)
        if not obsidian_path.exists():
            console.print(
                f"  [yellow]Note: {obsidian_path} does not exist yet. "
                f"Create it before running sync.[/yellow]\n"
            )
        else:
            console.print(f"  [green]Found vault at {obsidian_path}[/green]\n")
    else:
        console.print("  [dim]Skipped — you can set obsidian_base in config.yaml later.[/dim]\n")

    # ------------------------------------------------------------------
    # Step 5 — Write config
    # ------------------------------------------------------------------
    console.print("[bold]Step 5 of 5[/bold]  Writing configuration...")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CONFIG_DIR / "config.yaml"

    # Preserve any existing keys by loading first, then merging
    existing: dict = {}
    if config_path.exists():
        with contextlib.suppress(yaml.YAMLError):
            existing = yaml.safe_load(config_path.read_text()) or {}

    # New values take precedence over existing
    merged = {**existing, **config}
    # Nested dicts: merge content and notebooklm sub-keys
    for key in ("content", "notebooklm"):
        if key in existing and key in config and isinstance(existing[key], dict):
            merged[key] = {**existing[key], **config[key]}

    config_path.write_text(yaml.dump(merged, default_flow_style=False, sort_keys=False))

    console.print(f"\n[bold green]Configuration saved to {config_path}[/bold green]")

    # ------------------------------------------------------------------
    # LAN access tip
    # ------------------------------------------------------------------
    console.print("\n[dim]Tip: To access the web dashboard from other devices on your LAN,[/dim]")
    console.print(f"[dim]set lan_username and lan_password in {config_path}[/dim]")

    # ------------------------------------------------------------------
    # Offer to launch web UI
    # ------------------------------------------------------------------
    console.print()
    launch = click.confirm("Launch the studyctl web UI now?", default=False)
    if launch:
        console.print("[dim]Starting web UI on http://localhost:8000 ...[/dim]")
        try:
            subprocess.Popen(
                ["studyctl", "web"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            console.print(
                "[green]Web UI started. Open http://localhost:8000 in your browser.[/green]"
            )
        except FileNotFoundError:
            console.print("[yellow]Could not launch web UI. Run 'studyctl web' manually.[/yellow]")
    else:
        console.print("\n[bold]You're all set.[/bold] Next steps:")
        console.print("  studyctl config show    — review your configuration")
        console.print("  studyctl review         — see what topics are due for review")
        console.print("  studyctl web            — open the web UI")
        console.print("  studyctl --help         — explore all commands")
