"""Agent definition health checks — detect AI tools, verify definitions current.

Checks:
  1. Which AI coding tools are installed (binary detection + smoke test)
  2. Whether agent definitions are installed and up-to-date (hash vs manifest)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from studyloop.doctor.models import CheckResult
from studyloop.harnesses import HARNESSES, RELEASE_HARNESSES
from studyloop.installers import find_repo_root

MANIFEST_URL = (
    "https://raw.githubusercontent.com/NetDevAutomate/StudyLoop/main/agents/manifest.json"
)

TOOL_AGENTS: dict[str, tuple[str, str]] = {
    "kiro": ("kiro-cli", "~/.kiro/agents/study-mentor.json"),
    "codex": ("codex", "{repo_root}/AGENTS.md"),
    "claude": ("claude", "~/.claude/agents/socratic-mentor.md"),
    "opencode": ("opencode", "~/.config/opencode/agents/study-mentor.md"),
    "pi": ("pi", "~/.pi/agent/AGENTS.md"),
}

assert tuple(TOOL_AGENTS) == RELEASE_HARNESSES
assert all(TOOL_AGENTS[name][0] == HARNESSES[name].binary for name in RELEASE_HARNESSES)

_SMOKE_TIMEOUT = 5  # seconds


def _detect_ai_tools() -> list[str]:
    return [name for name, (binary, _) in TOOL_AGENTS.items() if shutil.which(binary)]


def _get_agent_install_path(tool: str) -> Path:
    _, path_template = TOOL_AGENTS[tool]
    if "{repo_root}" in path_template:
        repo_root = find_repo_root(Path.cwd()) or Path.cwd()
        return Path(path_template.format(repo_root=repo_root)).expanduser()
    return Path(path_template).expanduser()


def _smoke_test(binary: str) -> tuple[bool, str]:
    """Run ``binary --version`` and return (ok, version_or_error).

    Catches missing binaries, permission errors, and timeouts.
    """
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=_SMOKE_TIMEOUT,
        )
        if result.returncode == 0:
            version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "ok"
            return True, version
        return False, f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "binary not found"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {_SMOKE_TIMEOUT}s"
    except Exception as exc:
        return False, str(exc)


def _fetch_manifest_with_reason() -> tuple[dict | None, str]:
    """Fetch the agent manifest, returning why it failed when it does.

    The reason matters: a 404 means the manifest is not reachable at that URL —
    typically because the repository is private, or the branch has moved — and
    telling the user to "check network connection" for that sends them to
    diagnose something that is working. Distinguish it from a genuine outage.
    """
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "studyloop-doctor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), ""
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None, "not-published"
        return None, "http-error"
    except (urllib.error.URLError, TimeoutError):
        return None, "offline"
    except json.JSONDecodeError:
        return None, "malformed"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def check_agent_smoke_tests() -> list[CheckResult]:
    """Run smoke tests on all detected AI tools."""
    tools = _detect_ai_tools()
    if not tools:
        return []

    results: list[CheckResult] = []
    for tool in tools:
        binary, _ = TOOL_AGENTS[tool]
        binary_path = shutil.which(binary) or binary
        ok, detail = _smoke_test(binary_path)
        if ok:
            results.append(
                CheckResult(
                    "agents",
                    f"smoke_{tool}",
                    "pass",
                    f"{tool} responds ({detail})",
                    "",
                    False,
                )
            )
        else:
            results.append(
                CheckResult(
                    "agents",
                    f"smoke_{tool}",
                    "warn",
                    f"{tool} installed but smoke test failed: {detail}",
                    f"Check {binary} installation",
                    False,
                )
            )
    return results


def check_agent_definitions() -> list[CheckResult]:
    """Check that agent definitions are installed and match the manifest."""
    tools = _detect_ai_tools()
    if not tools:
        return [
            CheckResult(
                "agents",
                "no_ai_tools",
                "info",
                "No AI coding tools detected",
                "Install Kiro CLI, Codex, Claude Code, OpenCode, or pi",
                False,
            )
        ]

    manifest, reason = _fetch_manifest_with_reason()
    if manifest is None:
        detail, fix = {
            "not-published": (
                "Agent manifest not published yet — agents install from this checkout",
                "studyloop install agents",
            ),
            "malformed": (
                "Agent manifest fetched but could not be parsed",
                "studyloop install agents",
            ),
            "http-error": (
                "Agent manifest fetch failed (server error)",
                "Retry later, or: studyloop install agents",
            ),
        }.get(
            reason,
            ("Could not fetch agent manifest (offline?)", "Check network connection"),
        )
        return [
            CheckResult(
                "agents",
                "manifest_fetch",
                "info",
                detail,
                fix,
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
                        "studyloop upgrade --component agents",
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
                        "studyloop upgrade --component agents",
                        fix_auto=True,
                    )
                )
            break

    return results
