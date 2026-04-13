"""Shared CLI utilities — console, helpers, constants."""

from __future__ import annotations

from pathlib import Path

from click import ClickException

from studyctl.installers import InstallError, install_agent_definitions, require_repo_root
from studyctl.output import console
from studyctl.topics import Topic, get_topics

# Topic keywords for session DB queries
TOPIC_KEYWORDS = {
    "python": [
        "python",
        "pattern",
        "dataclass",
        "protocol",
        "abc",
        "strategy",
        "bridge",
        "decorator",
    ],
    "sql": ["sql", "query", "join", "index", "postgresql", "athena", "redshift", "window function"],
    "data-engineering": [
        "spark",
        "glue",
        "pipeline",
        "etl",
        "airflow",
        "dbt",
        "kafka",
        "partition",
        "dag",
    ],
    "aws-analytics": ["sagemaker", "athena", "redshift", "lake formation", "emr", "glue catalog"],
}


def get_topic(name: str) -> Topic | None:
    """Find a topic by name (exact or substring match)."""
    for t in get_topics():
        if t.name == name or name in t.name:
            return t
    return None


def offer_agent_install(flag: bool | None) -> None:
    """Offer to install AI agent definitions after config init.

    Args:
        flag: True = install, False = skip, None = ask interactively.
    """
    if flag is None:
        console.print("\n[bold cyan]Agent Installation[/bold cyan]")
        console.print(
            "The study mentor agents can be installed for detected AI tools\n"
            "(Claude Code, Codex CLI, Kiro CLI, Gemini, OpenCode, Amp).\n"
        )
        reply = input("Install agent definitions now? [Y/n] ").strip().lower()
        flag = reply in ("", "y", "yes")

    if flag:
        try:
            repo_root = require_repo_root(Path.cwd())
            summary = install_agent_definitions(repo_root)
        except (InstallError, OSError) as exc:
            console.print(f"[yellow]Agent install skipped:[/yellow] {exc}")
            return
        except ClickException as exc:
            console.print(f"[yellow]Agent install skipped:[/yellow] {exc}")
            return

        console.print("[green]Agent definitions installed.[/green]")
        for name, count in summary.items():
            console.print(f"  {name}: {count}")
