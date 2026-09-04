"""Cross-machine state sync using agent-session-tools infrastructure.

Uses the existing session-sync merge logic (SQLite + rsync) rather than
reinventing sync. One machine acts as the hub — all machines push/pull to it.

Config lives at ~/.config/studyloop/config.yaml

Host schema:
  hosts:
    hub:
      hostname: study-hub
      ip_address:
        primary: 192.168.1.20
        secondary: 192.168.1.21   # optional, fallback for wifi
      user: alex
      state_json: ~/.config/studyloop/state.json
      sessions_db: ~/.config/studyloop/sessions.db

Local machine is auto-detected by matching socket.gethostname() against
the hostname field in each host entry.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import yaml

from .settings import get_config_path, load_raw_config, load_settings, write_raw_config

CONFIG_PATH = get_config_path()
_DEFAULT_CONFIG_PATH = CONFIG_PATH


def _active_config_path() -> Path:
    """Return active config path while preserving old test monkeypatch hooks."""
    if os.environ.get("STUDYLOOP_CONFIG"):
        return get_config_path()
    if CONFIG_PATH != _DEFAULT_CONFIG_PATH:
        return CONFIG_PATH
    return get_config_path()


def _get_default_user() -> str:
    """Get default sync user lazily (avoids import-time os.getlogin failure)."""
    return load_settings().sync_user


def _load_config() -> dict:
    config_path = _active_config_path()
    if config_path == get_config_path():
        return load_raw_config()
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def _resolve_hosts(config: dict) -> tuple[str | None, dict, dict[str, dict]]:
    """Resolve local and remote hosts from unified hosts config.

    Returns:
        (local_name, local_host_config, remote_hosts_dict)
    """
    hosts = config.get("hosts", {})

    # Auto-detect local machine by hostname
    current_hostname = socket.gethostname().split(".")[0]
    local_name: str | None = None
    local_config: dict = {}
    remotes: dict[str, dict] = {}

    for name, host in hosts.items():
        if host.get("hostname") == current_hostname:
            local_name = name
            local_config = host
        else:
            remotes[name] = host

    return local_name, local_config, remotes


def _get_host_ip(host_config: dict) -> str:
    """Get the primary IP address for a host."""
    ip = host_config.get("ip_address", {})
    if isinstance(ip, dict):
        return ip.get("primary", "")
    return str(ip) if ip else ""


def _get_host_ips(host_config: dict) -> list[str]:
    """Get all IP addresses for a host (primary first, then secondary)."""
    ip = host_config.get("ip_address", {})
    if isinstance(ip, dict):
        ips = []
        if ip.get("primary"):
            ips.append(ip["primary"])
        if ip.get("secondary"):
            ips.append(ip["secondary"])
        return ips
    return [str(ip)] if ip else []


def _rsync_with_fallback(
    args_template: list[str], host_config: dict, user: str
) -> subprocess.CompletedProcess:
    """Run rsync trying primary IP, falling back to secondary."""
    ips = _get_host_ips(host_config)
    last_result = None
    for ip in ips:
        # Replace {dest} placeholder with actual user@ip
        args = [a.replace("{HOST}", f"{user}@{ip}") for a in args_template]
        last_result = subprocess.run(args, capture_output=True, text=True)
        if last_result.returncode == 0:
            return last_result
    # Return last failure if all IPs failed
    return last_result or subprocess.CompletedProcess(args_template, 1)


def push_state(remote: str | None = None) -> list[str]:
    """Push studyloop state + sessions DB to remote machine(s).

    Uses rsync for state.json and session-sync for the sessions DB
    (which handles intelligent merging, FTS rebuild, etc.)
    """
    config = _load_config()
    if not config:
        raise FileNotFoundError(
            f"No config at {_active_config_path()}. Run 'studyloop state init'."
        )

    _, local_config, remotes = _resolve_hosts(config)
    if remote:
        remotes = {remote: remotes[remote]} if remote in remotes else {}

    pushed = []
    state_json = Path(local_config.get("state_json", "~/.config/studyloop/state.json")).expanduser()

    for name, r in remotes.items():
        user = r.get("user", _get_default_user())
        remote_state = r.get("state_json", "~/.config/studyloop/state.json")

        # Push state.json via rsync (with IP fallback)
        if state_json.exists():
            result = _rsync_with_fallback(
                ["rsync", "-az", str(state_json), f"{{HOST}}:{remote_state}"],
                r,
                user,
            )
            if result.returncode == 0:
                pushed.append(f"state.json → {name}")

        # Push sessions DB via session-sync (handles merge)
        sessions_db = Path(local_config.get("sessions_db", "")).expanduser()
        if sessions_db.exists():
            remote_db = r.get("sessions_db", "")
            if remote_db:
                ip = _get_host_ip(r)
                dest = f"{user}@{ip}:{remote_db}"
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
        raise FileNotFoundError(f"No config at {_active_config_path()}")

    _, local_config, remotes = _resolve_hosts(config)
    if remote:
        remotes = {remote: remotes[remote]} if remote in remotes else {}

    pulled = []
    state_json = Path(local_config.get("state_json", "~/.config/studyloop/state.json")).expanduser()
    state_json.parent.mkdir(parents=True, exist_ok=True)

    for name, r in remotes.items():
        user = r.get("user", _get_default_user())
        remote_state = r.get("state_json", "~/.config/studyloop/state.json")

        # Pull state.json (with IP fallback)
        result = _rsync_with_fallback(
            ["rsync", "-az", "--update", f"{{HOST}}:{remote_state}", str(state_json)],
            r,
            user,
        )
        if result.returncode == 0:
            pulled.append(f"state.json ← {name}")

        # Pull + merge sessions DB
        remote_db = r.get("sessions_db", "")
        if remote_db:
            ip = _get_host_ip(r)
            src = f"{user}@{ip}:{remote_db}"
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
        return {"configured": False, "config_path": str(_active_config_path())}

    local_name, _, remotes = _resolve_hosts(config)

    status: dict = {
        "configured": True,
        "local": local_name or "unknown",
        "remotes": {},
    }
    for name, r in remotes.items():
        ips = _get_host_ips(r)
        user = r.get("user", _get_default_user())
        reachable = False
        connected_ip = ""

        for ip in ips:
            result = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "ConnectTimeout=3",
                    "-o",
                    "BatchMode=yes",
                    f"{user}@{ip}",
                    "echo ok",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                reachable = True
                connected_ip = ip
                break

        status["remotes"][name] = {
            "host": connected_ip or (ips[0] if ips else "?"),
            "reachable": reachable,
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

    config_path = _active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or start fresh
    existing: dict = {}
    if config_path.exists():
        existing = _load_config()
        console.print(f"[dim]Existing config found at {config_path} — updating.[/dim]\n")

    console.print(
        Panel(
            "[bold]StudyLoop — Interactive Setup[/bold]\n\n"
            "This will configure your study environment.\n"
            "Press Enter to accept defaults shown in [dim]brackets[/dim].",
            title="🧠 studyloop config init",
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
            "  [dim]You can add specific anchor concepts later with: studyloop bridge add[/dim]\n"
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
            "  [dim]  studyloop sync <topic>  — syncs Obsidian notes to a NotebookLM notebook[/dim]"
        )
        console.print("  [dim]  Requires: uv pip install 'studyloop[notebooklm]'[/dim]\n")
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
    publish_to_vault = False
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

        # Asked only AFTER a vault was accepted, and only ever defaulting to No.
        # A vault configured so the mentor can READ notes is not consent to start
        # WRITING into it, and a default-Yes would opt people in through a prompt
        # they skimmed. Answering No writes nothing at all: absence already means
        # off, and a config full of explicit defaults invites the belief that
        # deleting a key changes behaviour.
        publish_to_vault = _prompt_yn(
            "  Also publish your study plans and today's study into this vault\n"
            "  (a Study/ folder StudyLoop owns)?",
            default=False,
        )
        if publish_to_vault:
            console.print(
                "  [dim]StudyLoop will write into Study/ and never touch your own "
                "notes. Publish with: studyloop brain publish[/dim]\n"
            )
        else:
            console.print("  [dim]Skipped — nothing will be written to your vault.[/dim]\n")
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

    if publish_to_vault:
        # Merged, not replaced: a learner who set daily_note or a folder by hand
        # must not lose it by re-running the wizard.
        second_brain = dict(config.get("second_brain") or {})
        second_brain["provider"] = "obsidian"
        second_brain["vault_path"] = obsidian_base
        config["second_brain"] = second_brain

    # Ensure topics key exists
    config.setdefault("topics", [])

    if config_path == get_config_path():
        return write_raw_config(config)
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return config_path


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
    """Create default config file with unified hosts schema."""
    config_path = _active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        return config_path

    hostname = socket.gethostname().split(".")[0]
    default = {
        "hosts": {
            hostname.lower().replace(" ", "-"): {
                "hostname": hostname,
                "ip_address": {
                    "primary": "",
                },
                "user": _get_default_user(),
                "state_json": "~/.config/studyloop/state.json",
                "sessions_db": "~/.config/studyloop/sessions.db",
            },
        },
    }
    if config_path == get_config_path():
        return write_raw_config(default)
    config_path.write_text(yaml.dump(default, default_flow_style=False, sort_keys=False))
    return config_path
