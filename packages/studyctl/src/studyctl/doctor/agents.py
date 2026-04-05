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

from studyctl.doctor.models import CheckResult

MANIFEST_URL = "https://raw.githubusercontent.com/NetDevAutomate/socratic-study-mentor/main/agents/manifest.json"

TOOL_AGENTS: dict[str, tuple[str, str]] = {
    "claude": ("claude", "~/.claude/commands/socratic-mentor.md"),
    "kiro": ("kiro-cli", "~/.kiro/agents/study-mentor.json"),
    "gemini": ("gemini", "~/.gemini/agents/study-mentor.md"),
    "opencode": ("opencode", "~/.config/opencode/agents/study-mentor.md"),
}

_SMOKE_TIMEOUT = 5  # seconds


def _detect_ai_tools() -> list[str]:
    return [name for name, (binary, _) in TOOL_AGENTS.items() if shutil.which(binary)]


def _get_agent_install_path(tool: str) -> Path:
    _, path_template = TOOL_AGENTS[tool]
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


def _fetch_manifest() -> dict | None:
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "studyctl-doctor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


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


def check_local_llm_servers() -> list[CheckResult]:
    """Check Ollama and LM Studio availability — binary, server, and claude dependency."""
    results: list[CheckResult] = []
    claude_installed = bool(shutil.which("claude"))

    # Ollama
    ollama_bin = shutil.which("ollama")
    if ollama_bin:
        if not claude_installed:
            results.append(
                CheckResult(
                    "agents",
                    "ollama_claude",
                    "warn",
                    "ollama installed but claude not found (required as frontend)",
                    "Install Claude Code: npm i -g @anthropic-ai/claude-code",
                    False,
                )
            )
        # Check server is running by listing models
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=_SMOKE_TIMEOUT,
            )
            if result.returncode == 0:
                # Count models (skip header line)
                lines = [line for line in result.stdout.strip().splitlines()[1:] if line.strip()]
                n = len(lines)
                results.append(
                    CheckResult(
                        "agents",
                        "ollama_server",
                        "pass",
                        f"ollama running, {n} model{'s' if n != 1 else ''} available",
                        "",
                        False,
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "agents",
                        "ollama_server",
                        "warn",
                        "ollama installed but server not responding",
                        "Start with: ollama serve",
                        False,
                    )
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            results.append(
                CheckResult(
                    "agents",
                    "ollama_server",
                    "warn",
                    "ollama installed but server not responding",
                    "Start with: ollama serve",
                    False,
                )
            )

    # LM Studio
    lms_bin = shutil.which("lms")
    if lms_bin:
        if not claude_installed:
            results.append(
                CheckResult(
                    "agents",
                    "lmstudio_claude",
                    "warn",
                    "lms installed but claude not found (required as frontend)",
                    "Install Claude Code: npm i -g @anthropic-ai/claude-code",
                    False,
                )
            )
        # Probe the API endpoint
        try:
            result = subprocess.run(
                ["lms", "status"],
                capture_output=True,
                text=True,
                timeout=_SMOKE_TIMEOUT,
            )
            status = "pass" if result.returncode == 0 else "warn"
            msg = (
                "LM Studio server running"
                if result.returncode == 0
                else "LM Studio CLI found but server not responding"
            )
            hint = "" if result.returncode == 0 else "Start LM Studio and load a model"
            results.append(CheckResult("agents", "lmstudio_server", status, msg, hint, False))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            results.append(
                CheckResult(
                    "agents",
                    "lmstudio_server",
                    "warn",
                    "LM Studio CLI found but server not responding",
                    "Start LM Studio and load a model",
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
                "Install Claude Code, Kiro CLI, Gemini CLI, or OpenCode",
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
