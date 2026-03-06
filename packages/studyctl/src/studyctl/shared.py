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
_DEFAULT_USER = load_settings().sync_user


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
        user = r.get("user", _DEFAULT_USER)
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
        user = r.get("user", _DEFAULT_USER)
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
                f"{r.get('user', _DEFAULT_USER)}@{host}",
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


def init_config() -> Path:
    """Create default config file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return CONFIG_PATH

    default = {
        "local": {
            "name": "work-macbook",
            "state_json": "~/.local/share/studyctl/state.json",
            "sessions_db": "~/code/personal/ai/extract_session_to_db/sessions.db",
        },
        "remotes": {
            "mac-mini": {
                "host": "mac-mini.local",
                "user": _DEFAULT_USER,
                "state_json": "~/.local/share/studyctl/state.json",
                "sessions_db": "~/code/personal/ai/extract_session_to_db/sessions.db",
            },
        },
    }
    CONFIG_PATH.write_text(yaml.dump(default, default_flow_style=False))
    return CONFIG_PATH
