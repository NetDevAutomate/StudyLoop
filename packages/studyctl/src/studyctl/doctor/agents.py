"""Agent definition health checks — detect AI tools, verify definitions current."""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from studyctl.doctor.models import CheckResult

MANIFEST_URL = "https://raw.githubusercontent.com/NetDevAutomate/socratic-study-mentor/main/agents/manifest.json"

TOOL_AGENTS: dict[str, tuple[str, str]] = {
    "claude": ("claude", "~/.claude/commands/socratic-mentor.md"),
    "kiro": ("kiro", "~/.kiro/agents/study-mentor/agent.yml"),
    "gemini": ("gemini", "~/.gemini/agents/study-mentor.md"),
    "opencode": ("opencode", "~/.config/opencode/agents/study-mentor.md"),
}


def _detect_ai_tools() -> list[str]:
    return [name for name, (binary, _) in TOOL_AGENTS.items() if shutil.which(binary)]


def _get_agent_install_path(tool: str) -> Path:
    _, path_template = TOOL_AGENTS[tool]
    return Path(path_template).expanduser()


def _fetch_manifest() -> dict | None:
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "studyctl-doctor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def check_agent_definitions() -> list[CheckResult]:
    tools = _detect_ai_tools()
    if not tools:
        return [
            CheckResult(
                "agents",
                "no_ai_tools",
                "info",
                "No AI coding tools detected",
                "Install Claude Code, Kiro, Gemini CLI, or OpenCode",
                False,
            )
        ]

    manifest = _fetch_manifest()
    if manifest is None:
        return [
            CheckResult(
                "agents",
                "manifest_fetch",
                "info",
                "Could not fetch agent manifest (offline?)",
                "Check network connection",
                False,
            )
        ]

    results: list[CheckResult] = []
    manifest_agents = manifest.get("agents", {})

    for tool in tools:
        install_path = _get_agent_install_path(tool)
        tool_keys = [k for k in manifest_agents if k.startswith(f"{tool}/")]
        if not tool_keys:
            results.append(
                CheckResult(
                    "agents", f"agent_{tool}", "info", f"No manifest entry for {tool}", "", False
                )
            )
            continue

        for key in tool_keys:
            if not install_path.exists():
                results.append(
                    CheckResult(
                        "agents",
                        f"agent_{tool}",
                        "warn",
                        f"{tool} detected but agent definition not installed",
                        "studyctl upgrade --component agents",
                        fix_auto=True,
                    )
                )
                break

            local_hash = _hash_file(install_path)
            expected_hash = manifest_agents[key]["hash"]
            if local_hash == expected_hash:
                results.append(
                    CheckResult(
                        "agents",
                        f"agent_{tool}",
                        "pass",
                        f"{tool} agent definition current",
                        "",
                        False,
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "agents",
                        f"agent_{tool}",
                        "warn",
                        (
                            f"{tool} agent definition outdated"
                            f" (local={local_hash[:8]}... expected={expected_hash[:8]}...)"
                        ),
                        "studyctl upgrade --component agents",
                        fix_auto=True,
                    )
                )
            break

    return results
