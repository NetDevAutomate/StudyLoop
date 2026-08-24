"""Cross-machine state sync using agent-session-tools infrastructure.

Uses the existing session-sync merge logic (SQLite + rsync) rather than
reinventing sync. The Mac Mini acts as the hub — all machines push/pull to it.

Config lives at ~/.config/studyloop/config.yaml

Host schema:
  hosts:
    macmini:
      hostname: study-hub
      ip_address:
        primary: 192.168.1.22
        secondary: 192.168.1.12   # optional, fallback for wifi
      user: user
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
