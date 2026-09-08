"""Idempotent `session-db` MCP registration per harness (WP-2, pack-phase2 §4.1–4.5).

Each merge function edits exactly one harness config file, preserves every unrelated
key, and uses the presence of the ``session-db`` name as its idempotency sentinel.
Writes are atomic (tmp file + ``os.replace``). Config shapes:

- Claude   ``~/.claude.json``                       → ``mcpServers`` (JSON object)
- Kiro     ``~/.kiro/settings/mcp.json``            → ``mcpServers`` (JSON object)
- OpenCode ``~/.config/opencode/opencode.json``     → ``mcp`` (JSON, array command)
- Codex    ``~/.codex/config.toml``                 → ``[mcp_servers.*]`` (TOML)
- Grok     ``~/.grok/config.toml``                  → Codex shape (TOML)
- pi       — NO verified registry. The plan's surveyed path
  (``~/.pi/agent/compound-engineering/mcporter.json``) belongs to the third-party
  compound-engineering plugin, not to pi itself; pi's own ``settings.json`` carries
  no ``mcpServers`` section and ``mcp-cache.json`` is derived state, not a registry.

Codex/Grok TOML shapes need a style-preserving writer (tomlkit) that this package
does not yet depend on. Those three merge functions fail closed with instructions
rather than guessing at a lossy or misdirected rewrite of a user config.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

NAME = "session-db"

DEFAULT_PATHS: dict[str, str] = {
    "claude": ".claude.json",
    "codex": ".codex/config.toml",
    "kiro": ".kiro/settings/mcp.json",
    "opencode": ".config/opencode/opencode.json",
    "grok": ".grok/config.toml",
}


class InstallError(RuntimeError):
    """A harness config cannot be merged safely."""


def _merge_json(path: Path, *, key: str, entry: dict, dry_run: bool) -> bool:
    """Merge ``entry`` under ``key`` in a JSON config; sentinel is NAME's presence.

    Returns True when a write happened (or would happen under ``dry_run``);
    False when the harness is already registered. Unrelated keys are preserved.
    """
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"{path}: unreadable or invalid JSON ({exc})") from exc
        if not isinstance(loaded, dict):
            raise InstallError(f"{path} is not a JSON object")
        data = loaded
    else:
        data = {}
    section = data.setdefault(key, {})
    if not isinstance(section, dict):
        raise InstallError(f"{path}: {key} is not an object")
    if NAME in section:
        return False
    if dry_run:
        return True
    section[NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return True


def merge_claude_mcp(path: Path, *, dry_run: bool = False) -> bool:
    return _merge_json(
        path,
        key="mcpServers",
        entry={"type": "stdio", "command": "session-db-mcp", "args": [], "env": {}},
        dry_run=dry_run,
    )


def merge_kiro_mcp(path: Path, *, dry_run: bool = False) -> bool:
    return _merge_json(
        path, key="mcpServers", entry={"command": "session-db-mcp"}, dry_run=dry_run
    )


def merge_opencode_mcp(path: Path, *, dry_run: bool = False) -> bool:
    return _merge_json(
        path,
        key="mcp",
        entry={"command": ["session-db-mcp"], "enabled": True, "type": "local"},
        dry_run=dry_run,
    )


def _merge_toml_unsupported(path: Path, *, dry_run: bool = False) -> bool:
    raise InstallError(
        f"{path}: TOML merge needs a style-preserving writer (tomlkit) that this "
        f"package does not yet depend on; add [mcp_servers.{NAME}] with "
        'command = "session-db-mcp" manually'
    )


def _merge_pi_unverified(path: Path, *, dry_run: bool = False) -> bool:
    raise InstallError(
        "pi has no verified user-editable MCP registry: the surveyed path belongs to "
        "the third-party compound-engineering plugin and pi's settings.json has no "
        "mcpServers section; register through pi's own extension/package mechanism"
    )


MERGERS = {
    "claude": merge_claude_mcp,
    "kiro": merge_kiro_mcp,
    "opencode": merge_opencode_mcp,
    "pi": _merge_pi_unverified,
    "codex": _merge_toml_unsupported,
    "grok": _merge_toml_unsupported,
}


def register_mcp(
    harness: str, *, home: Path | None = None, dry_run: bool = False
) -> bool:
    """Register ``session-db`` for one harness at its default config path.

    Returns True when a write happened (or would, under ``dry_run``); False when
    already registered. Raises :class:`InstallError` for unknown harnesses,
    unmergeable configs, and the not-yet-supported TOML shapes.
    """
    if harness not in MERGERS:
        known = ", ".join(sorted(MERGERS))
        raise InstallError(f"unknown harness {harness!r}; known: {known}")
    base = home or Path.home()
    # pi has no verified registry path; its merger fails closed regardless.
    target = base / DEFAULT_PATHS[harness] if harness in DEFAULT_PATHS else base
    return MERGERS[harness](target, dry_run=dry_run)
