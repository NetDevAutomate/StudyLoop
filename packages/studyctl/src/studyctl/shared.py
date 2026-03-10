"""Cross-machine state sync using agent-session-tools infrastructure.

Uses the existing session-sync merge logic (SQLite + rsync) rather than
reinventing sync. The Mac Mini acts as the hub — all machines push/pull to it.

Config lives at ~/.config/studyctl/config.yaml
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from .settings import load_settings

CONFIG_PATH = Path.home() / ".config" / "studyctl" / "config.yaml"


def _get_default_user() -> str:
    """Get default sync user lazily (avoids import-time os.getlogin failure)."""
    return load_settings().sync_user


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def push_state(remote: str | None = None) -> list[str]:
    """Push studyctl state + sessions DB to remote machine(s).

    Uses rsync for state.json and session-sync for the sessions DB
    (which handles intelligent merging, FTS rebuild, etc.)
    """
    config = _load_config()
    if not config:
        raise FileNotFoundError(f"No config at {CONFIG_PATH}. Run 'studyctl state init'.")

    local = config.get("local", {})
    remotes = config.get("remotes", {})
    if remote:
        remotes = {remote: remotes[remote]} if remote in remotes else {}

    pushed = []
    state_json = Path(local.get("state_json", "~/.local/share/studyctl/state.json")).expanduser()

    for name, r in remotes.items():
        host = r["host"]
        user = r.get("user", _get_default_user())
        remote_state = r.get("state_json", "~/.local/share/studyctl/state.json")

        # Push state.json via rsync
        if state_json.exists():
            dest = f"{user}@{host}:{remote_state}"
            result = subprocess.run(
                ["rsync", "-az", str(state_json), dest],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pushed.append(f"state.json → {name}")

        # Push sessions DB via session-sync (handles merge)
        sessions_db = Path(local.get("sessions_db", "")).expanduser()
        if sessions_db.exists():
            remote_db = r.get("sessions_db", "")
            if remote_db:
                dest = f"{user}@{host}:{remote_db}"
                result = subprocess.run(
                    ["session-sync", "push", dest],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    pushed.append(f"sessions.db → {name}")

    return pushed


def pull_state(remote: str | None = None) -> list[str]:
    """Pull state from remote machine(s). Sessions DB uses merge logic."""
    config = _load_config()
    if not config:
        raise FileNotFoundError(f"No config at {CONFIG_PATH}")

    local = config.get("local", {})
    remotes = config.get("remotes", {})
    if remote:
        remotes = {remote: remotes[remote]} if remote in remotes else {}

    pulled = []
    state_json = Path(local.get("state_json", "~/.local/share/studyctl/state.json")).expanduser()
    state_json.parent.mkdir(parents=True, exist_ok=True)

    for name, r in remotes.items():
        host = r["host"]
        user = r.get("user", _get_default_user())
        remote_state = r.get("state_json", "~/.local/share/studyctl/state.json")

        # Pull state.json — take most recent
        src = f"{user}@{host}:{remote_state}"
        result = subprocess.run(
            ["rsync", "-az", "--update", src, str(state_json)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            pulled.append(f"state.json ← {name}")

        # Pull + merge sessions DB
        remote_db = r.get("sessions_db", "")
        if remote_db:
            src = f"{user}@{host}:{remote_db}"
            result = subprocess.run(
                ["session-sync", "pull", src],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pulled.append(f"sessions.db ← {name} (merged)")

    return pulled


def sync_status() -> dict:
    """Check config and connectivity."""
    config = _load_config()
    if not config:
        return {"configured": False, "config_path": str(CONFIG_PATH)}

    status = {
        "configured": True,
        "local": config.get("local", {}).get("name", "unknown"),
        "remotes": {},
    }
    for name, r in config.get("remotes", {}).items():
        host = r["host"]
        # Quick SSH connectivity check
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=3",
                "-o",
                "BatchMode=yes",
                f"{r.get('user', _get_default_user())}@{host}",
                "echo ok",
            ],
            capture_output=True,
            text=True,
        )
        status["remotes"][name] = {
            "host": host,
            "reachable": result.returncode == 0,
        }
    return status


def init_interactive_config(console: object) -> Path:
    """Run interactive configuration wizard asking core setup questions.

    Asks about:
    1. Knowledge bridging — leverage familiar topics for analogies
    2. NotebookLM integration
    3. Obsidian vault path
    """
    from rich.console import Console
    from rich.panel import Panel

    if not isinstance(console, Console):
        console = Console()

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    existing: dict = {}
    if CONFIG_PATH.exists():
        existing = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        console.print(f"[dim]Existing config found at {CONFIG_PATH} — updating.[/dim]\n")

    console.print(
        Panel(
            "[bold]Socratic Study Mentor — Interactive Setup[/bold]\n\n"
            "This will configure your study environment.\n"
            "Press Enter to accept defaults shown in [dim]brackets[/dim].",
            title="🧠 studyctl config init",
            border_style="cyan",
        )
    )

    # ── Question 1: Knowledge bridging ──────────────────────────────────────
    console.print("\n[bold cyan]1/3 — Knowledge Bridging[/bold cyan]")
    console.print(
        "The study mentor can draw analogies between topics you already know well\n"
        "and new topics you're studying (e.g. networking → data engineering).\n"
    )

    use_bridging = _prompt_yn(
        "Do you want to leverage a topic you are already very familiar with\n"
        "  so we can draw comparisons with an area you already know well\n"
        "  to topics you are studying?",
        default=True,
    )

    knowledge_domains: dict = existing.get("knowledge_domains", {})
    if use_bridging:
        current_primary = knowledge_domains.get("primary", "")
        primary_domain = _prompt_text(
            "  What is your primary area of expertise?",
            default=current_primary or "networking",
        )
        knowledge_domains["primary"] = primary_domain

        console.print(
            f"\n  [dim]Great — the mentor will use {primary_domain} analogies"
            " to teach new concepts.[/dim]"
        )
        console.print(
            "  [dim]You can add specific anchor concepts later with: studyctl bridge add[/dim]\n"
        )
    else:
        knowledge_domains = {}
        console.print("  [dim]Skipped — no knowledge bridging configured.[/dim]\n")

    # ── Question 2: NotebookLM integration ──────────────────────────────────
    console.print("[bold cyan]2/3 — Google NotebookLM Integration[/bold cyan]")
    console.print(
        "NotebookLM can be used as a knowledge source — sync your notes into\n"
        "notebooks for AI-generated audio overviews and enhanced study sessions.\n"
    )

    use_notebooklm = _prompt_yn(
        "Do you want to integrate with Google's NotebookLM to use new and\n"
        "  existing Notebooks as a source of knowledge?",
        default=bool(existing.get("notebooklm", {}).get("enabled")),
    )

    notebooklm_config: dict = existing.get("notebooklm", {})
    if use_notebooklm:
        notebooklm_config["enabled"] = True
        console.print("\n  [dim]NotebookLM enabled. Map notebooks to topics via:[/dim]")
        console.print(
            "  [dim]  studyctl sync <topic>  — syncs Obsidian notes to a NotebookLM notebook[/dim]"
        )
        console.print("  [dim]  Requires: uv pip install 'studyctl[notebooklm]'[/dim]\n")
    else:
        notebooklm_config["enabled"] = False
        console.print("  [dim]Skipped — NotebookLM integration disabled.[/dim]\n")

    # ── Question 3: Obsidian vault ──────────────────────────────────────────
    console.print("[bold cyan]3/3 — Obsidian Vault Integration[/bold cyan]")
    console.print(
        "The study mentor can read your Obsidian vault for study notes,\n"
        "course materials, and knowledge base content.\n"
    )

    current_obsidian = str(existing.get("obsidian_base", "~/Obsidian"))
    use_obsidian = _prompt_yn(
        "Do you want to integrate with an existing Obsidian vault for sources\n  of information?",
        default=True,
    )

    obsidian_base = current_obsidian
    if use_obsidian:
        obsidian_base = _prompt_text(
            "  Base path of your Obsidian vault",
            default=current_obsidian,
        )
        resolved = Path(obsidian_base).expanduser()
        if resolved.exists():
            console.print(f"  [green]✓ Found vault at {resolved}[/green]\n")
        else:
            console.print(
                f"  [yellow]⚠ Path {resolved} does not exist yet — "
                f"you can create it later.[/yellow]\n"
            )
    else:
        obsidian_base = ""
        console.print("  [dim]Skipped — no Obsidian vault configured.[/dim]\n")

    # ── Write config ────────────────────────────────────────────────────────
    config = dict(existing)
    if obsidian_base:
        config["obsidian_base"] = obsidian_base
    elif "obsidian_base" in config:
        del config["obsidian_base"]

    if knowledge_domains:
        config["knowledge_domains"] = knowledge_domains
    elif "knowledge_domains" in config:
        del config["knowledge_domains"]

    config["notebooklm"] = notebooklm_config

    # Ensure topics key exists
    config.setdefault("topics", [])

    CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return CONFIG_PATH


def _prompt_yn(question: str, default: bool = False) -> bool:
    """Prompt for yes/no with a default."""
    suffix = " [Y/n] " if default else " [y/N] "
    reply = input(question + suffix).strip().lower()
    if not reply:
        return default
    return reply in ("y", "yes")


def _prompt_text(question: str, default: str = "") -> str:
    """Prompt for text input with a default."""
    suffix = f" [{default}] " if default else " "
    reply = input(question + suffix).strip()
    return reply or default


def init_config() -> Path:
    """Create default config file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return CONFIG_PATH

    import socket

    hostname = socket.gethostname().split(".")[0]
    default = {
        "local": {
            "name": hostname,
            "state_json": "~/.local/share/studyctl/state.json",
            "sessions_db": "~/.config/studyctl/sessions.db",
        },
        "remotes": {},
    }
    CONFIG_PATH.write_text(yaml.dump(default, default_flow_style=False))
    return CONFIG_PATH
