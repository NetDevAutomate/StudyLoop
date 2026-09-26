"""Agent definition health checks — detect AI tools, verify definitions current.

Checks:
  1. Which AI coding tools are installed (binary detection + smoke test)
  2. Whether agent definitions are installed and up-to-date (hash vs manifest)
  3. Whether kiro-cli can load StudyLoop's own ``studyloop`` agent, the one
     every Kiro ACP session names
"""

from __future__ import annotations

import hashlib
import json
import re
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
    "pi": ("pi", "~/.pi/agent/AGENTS.md"),
    "opencode": ("opencode", "~/.config/opencode/agents/study-mentor.md"),
    # Deliberately the same repo-root AGENTS.md that Codex reads: Grok Build
    # discovers the AGENTS.md instruction-file family from the repository root
    # down to the working directory, so a second copy would only drift.
    "grok": ("grok", "{repo_root}/AGENTS.md"),
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


def _agent_definition_install_path(tool: str, key: str) -> Path | None:
    """Resolve the on-disk install path for one manifest key under ``tool``.

    The primary (canary) definition -- the one path per tool in
    :data:`TOOL_AGENTS`, used for the smoke test and long-standing currency
    check -- still resolves through :func:`_get_agent_install_path`, so tests
    that patch it keep working unchanged. Any OTHER manifest key sharing this
    tool's prefix (a second native agent definition, e.g.
    ``study-plan-architect.md`` alongside ``socratic-mentor.md``) resolves
    through the matching :data:`studyloop.installers._TOOL_LINKS` entry
    instead. This is what lets :func:`check_agent_definitions` report a new
    native definition by extending its existing loop rather than adding a
    parallel, hand-maintained table.

    A key whose link target is a directory (no file suffix -- e.g. Kiro's
    resources folder link) has no single file to hash, and is skipped.
    """
    primary_path = TOOL_AGENTS[tool][1]
    if Path(primary_path).name == Path(key).name:
        return _get_agent_install_path(tool)

    from studyloop.installers import _TOOL_LINKS

    repo_root = find_repo_root(Path.cwd()) or Path.cwd()
    for spec in _TOOL_LINKS.get(tool, ()):
        if spec.source != f"agents/{key}":
            continue
        if not Path(spec.source).suffix:
            return None
        return Path(spec.target.format(repo_root=repo_root)).expanduser()
    return None


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


#: StudyLoop's own Kiro agent, named on every Kiro ACP launch.
_KIRO_STUDYLOOP_AGENT = "~/.kiro/agents/studyloop.json"
#: ``agent list`` reads every agent file, so it gets longer than the smoke test.
_KIRO_AGENT_CHECK_TIMEOUT = 15  # seconds
#: ``kiro-cli agent list`` colours its scope column even when piped.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
#: An agent row in ``kiro-cli agent list``: the name starts at column 2, after
#: ``"  "`` or the default marker ``"* "``. Wrapped description lines are
#: indented far deeper, so a description mentioning an agent is never a row.
_AGENT_ROW = re.compile(r"^[* ] (\S+)\s+(.*)$")


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _error_line(text: str) -> str:
    """The first ``Error:`` line kiro-cli printed, colour and prefix removed.

    kiro-cli 2.24.0's ``agent validate`` exits 0 on an invalid file and states
    the verdict as ``Error: Json supplied at <path> is invalid: ...``.
    """
    for line in _ANSI_ESCAPE.sub("", text).splitlines():
        if line.strip().startswith("Error:"):
            return line.strip().removeprefix("Error:").strip()
    return ""


def _agent_list_rows(text: str) -> list[list[str]]:
    """``[name, scope-and-description...]`` for each agent row of ``agent list``."""
    rows: list[list[str]] = []
    for line in _ANSI_ESCAPE.sub("", text).splitlines():
        if match := _AGENT_ROW.match(line):
            rows.append([match.group(1), *match.group(2).split()])
    return rows


def check_kiro_studyloop_agent() -> list[CheckResult]:
    """Prove kiro-cli can load StudyLoop's own agent -- never the learner's default.

    Web ACP sessions run ``kiro-cli acp --agent studyloop``. Both questions that
    decide whether that works are put to kiro-cli itself rather than inferred
    from the file: ``agent validate`` (this kiro-cli accepts the config) and
    ``agent list`` (it discovers the agent, and no built-in agent of the same
    name shadows it -- the way kiro-cli 2.24.0's reserved ``kiro_default``
    silently ignored a learner's own ``kiro_default.json``). Silent when
    kiro-cli is not installed; the smoke test already reports that.

    This check is the only signal: an ``acp --agent`` naming an agent kiro-cli
    cannot load does not fail, it runs the built-in default. The parsing
    follows kiro-cli 2.24.0's real output (probed 2026-09-26): ``validate``
    exits 0 on an invalid file and reports it as an ``Error:`` line on stderr,
    and ``list`` writes its table to stderr.
    """
    from studyloop.adapters.kiro import KIRO_ACP_AGENT_NAME

    binary = shutil.which("kiro-cli")
    if not binary:
        return []

    name = "agent_kiro_studyloop_loads"
    path = Path(_KIRO_STUDYLOOP_AGENT).expanduser()
    if not path.exists():
        return [
            CheckResult(
                "agents",
                name,
                "warn",
                (
                    f"kiro {KIRO_ACP_AGENT_NAME} agent not installed"
                    " -- web (ACP) Kiro sessions need it"
                ),
                "studyloop install agents --tool kiro",
                fix_auto=True,
            )
        ]

    try:
        validated = subprocess.run(
            [binary, "agent", "validate", "--path", str(path)],
            capture_output=True,
            text=True,
            timeout=_KIRO_AGENT_CHECK_TIMEOUT,
        )
        # kiro-cli 2.24.0 exits 0 on an INVALID file; the verdict is an
        # `Error:` line on stderr. So both signals count.
        rejection = _error_line(validated.stderr) or _error_line(validated.stdout)
        if validated.returncode != 0 and not rejection:
            rejection = (
                _first_line(_ANSI_ESCAPE.sub("", validated.stderr))
                or _first_line(_ANSI_ESCAPE.sub("", validated.stdout))
                or f"exit code {validated.returncode}"
            )
        if rejection:
            return [
                CheckResult(
                    "agents",
                    name,
                    "warn",
                    f"kiro-cli rejects the {KIRO_ACP_AGENT_NAME} agent: {rejection}",
                    "studyloop install agents --tool kiro, then re-run studyloop doctor",
                    False,
                )
            ]
        listed = subprocess.run(
            [binary, "agent", "list"],
            capture_output=True,
            text=True,
            timeout=_KIRO_AGENT_CHECK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [
            CheckResult(
                "agents",
                name,
                "warn",
                f"could not ask kiro-cli about the {KIRO_ACP_AGENT_NAME} agent: {exc}",
                "Check kiro-cli installation",
                False,
            )
        ]

    # kiro-cli 2.24.0 writes the table to stderr; read both streams so a future
    # release that moves it to stdout still parses.
    ours = [
        row
        for row in _agent_list_rows(listed.stderr + "\n" + listed.stdout)
        if row[0] == KIRO_ACP_AGENT_NAME
    ]
    if any("(Built-in)" in row for row in ours):
        return [
            CheckResult(
                "agents",
                name,
                "warn",
                (
                    f"a built-in kiro-cli agent is also named {KIRO_ACP_AGENT_NAME}, so kiro-cli"
                    " ignores StudyLoop's agent file"
                ),
                "Report this to the StudyLoop maintainers: the agent needs a new name",
                False,
            )
        ]
    if not ours:
        return [
            CheckResult(
                "agents",
                name,
                "warn",
                (
                    f"kiro-cli does not list the {KIRO_ACP_AGENT_NAME} agent at {path}, so web"
                    " (ACP) Kiro sessions silently fall back to kiro-cli's built-in default"
                ),
                "studyloop install agents --tool kiro, then re-run studyloop doctor",
                False,
            )
        ]
    return [
        CheckResult(
            "agents",
            name,
            "pass",
            f"kiro {KIRO_ACP_AGENT_NAME} agent loads (kiro-cli validates and lists it)",
            "",
            False,
        )
    ]


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
                "Install Kiro CLI, Codex, Claude Code, OpenCode, pi, or Grok Build",
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
        tool_keys = [k for k in manifest_agents if k.startswith(f"{tool}/")]
        if not tool_keys:
            results.append(
                CheckResult(
                    "agents", f"agent_{tool}", "info", f"No manifest entry for {tool}", "", False
                )
            )
            continue

        primary_name = Path(TOOL_AGENTS[tool][1]).name
        for key in tool_keys:
            install_path = _agent_definition_install_path(tool, key)
            if install_path is None:
                continue  # e.g. a directory link with nothing to hash

            is_primary = Path(key).name == primary_name
            check_name = f"agent_{tool}" if is_primary else f"agent_{tool}_{Path(key).stem}"
            label = tool if is_primary else f"{tool} {Path(key).stem}"

            if not install_path.exists():
                results.append(
                    CheckResult(
                        "agents",
                        check_name,
                        "warn",
                        f"{tool} detected but agent definition not installed",
                        "studyloop upgrade --component agents",
                        fix_auto=True,
                    )
                )
                continue

            local_hash = _hash_file(install_path)
            expected_hash = manifest_agents[key]["hash"]
            if local_hash == expected_hash:
                results.append(
                    CheckResult(
                        "agents",
                        check_name,
                        "pass",
                        f"{label} agent definition current",
                        "",
                        False,
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "agents",
                        check_name,
                        "warn",
                        (
                            f"{label} agent definition outdated"
                            f" (local={local_hash[:8]}... expected={expected_hash[:8]}...)"
                        ),
                        "studyloop upgrade --component agents",
                        fix_auto=True,
                    )
                )

    return results


def check_mcp_registration() -> list[CheckResult]:
    """Report whether both StudyLoop MCP servers are registered per harness.

    Grok Build gets a richer message naming which file satisfied
    registration -- the legacy ``$GROK_HOME/user-settings.json`` map or the
    ``config.toml`` ``grok mcp add`` writes -- since the two are read from
    different sources and only one of them is StudyLoop-owned.
    """
    from studyloop.installers import _MCP_HARNESSES, _grok_registration_detail
    from studyloop.installers import mcp_registration_status as _status

    non_grok = [tool for tool in _MCP_HARNESSES if tool != "grok"]
    status = _status(non_grok)

    results: list[CheckResult] = []
    for tool in _MCP_HARNESSES:
        if tool == "grok":
            registered, source = _grok_registration_detail()
            message = (
                f"grok has session-db and studyloop MCP servers registered via {source}"
                if registered and source
                else "grok MCP registration is missing or incomplete"
            )
        else:
            registered = status[tool]
            message = (
                f"{tool} has session-db and studyloop MCP servers registered"
                if registered
                else f"{tool} MCP registration is missing or incomplete"
            )
        results.append(
            CheckResult(
                "agents",
                f"mcp_{tool}",
                "pass" if registered else "warn",
                message,
                "" if registered else "studyloop install agents",
                False,
            )
        )
    return results
