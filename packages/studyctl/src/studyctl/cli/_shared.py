"""Shared CLI utilities — console, helpers, constants."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from studyctl.topics import Topic, get_topics

console = Console()

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
    # Find install-agents.sh relative to the package
    candidate = Path(__file__).resolve().parent.parent
    for _ in range(6):
        script = candidate / "scripts" / "install-agents.sh"
        if script.exists():
            break
        candidate = candidate.parent
    else:
        return  # Script not found — skip silently (pip install, not git clone)

    if flag is None:
        console.print("\n[bold cyan]Agent Installation[/bold cyan]")
        console.print(
            "The study mentor agents can be installed for detected AI tools\n"
            "(Claude Code, Kiro CLI, Gemini, OpenCode, Amp).\n"
        )
        reply = input("Install agent definitions now? [Y/n] ").strip().lower()
        flag = reply in ("", "y", "yes")

    if flag:
        console.print("[dim]Running install-agents.sh...[/dim]")
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                console.print(f"  {line}")
        else:
            console.print("[yellow]Agent install had issues — run manually:[/yellow]")
            console.print(f"  bash {script}")
