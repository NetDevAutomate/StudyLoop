"""Doctor checks for cross-harness session-memory wiring.

For every detected release harness StudyLoop requires three independent layers:

1. ``session-query`` and ``session-export`` executables on PATH.
2. The canonical ``studyloop-session-memory`` skill reachable from that harness
   (MCP-first query with a deterministic CLI fallback).
3. A real native lifecycle hook that automatically exports that harness's
   transcript at session end. Prompt mandates are checked too, but do not count
   as hooks.

Every warning is repaired by the same top-level installer used by
``studyloop install agents`` so doctor and install cannot drift.
"""

from __future__ import annotations

import json
import shutil

from studyloop import installers
from studyloop.doctor.models import CheckResult

# Reference installer symbols through the module (not by direct import) so a
# test patching ``studyloop.installers._HARNESS_EXPORT`` / ``_HOME`` is seen
# here too, and so production always reads the live values.


def _steering_result(tool: str) -> CheckResult:
    spec = installers._HARNESS_EXPORT[tool]
    path = spec.steering_path
    present = path.exists() and installers._MANDATE_SENTINEL in path.read_text(encoding="utf-8")
    if present:
        return CheckResult(
            category="harness",
            name=f"export_mandate_{tool}",
            status="pass",
            message=f"{tool}: session-export mandate present in {path.name}",
            fix_hint="",
            fix_auto=False,
        )
    return CheckResult(
        category="harness",
        name=f"export_mandate_{tool}",
        status="warn",
        message=(
            f"{tool}: no session-export mandate in {path} — sessions/struggles "
            f"won't be persisted to the session DB at session end"
        ),
        fix_hint="studyloop doctor --fix  (writes the session-export steering mandate)",
        fix_auto=True,
    )


def _claude_hook_result() -> CheckResult:
    settings_path = installers._HOME / ".claude/settings.json"
    present = False
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            stop = (data.get("hooks", {}) or {}).get("Stop", []) or []
            for group in stop:
                if not isinstance(group, dict):
                    continue
                for h in group.get("hooks", []):
                    if installers._HOOK_SENTINEL in str(h.get("command", "")):
                        present = True
        except (OSError, json.JSONDecodeError):
            present = False
    if present:
        return CheckResult(
            category="harness",
            name="session_export_hook_claude",
            status="pass",
            message="claude: session-export Stop hook registered",
            fix_hint="",
            fix_auto=False,
        )
    return CheckResult(
        category="harness",
        name="session_export_hook_claude",
        status="warn",
        message=(
            "claude: no session-export Stop hook in ~/.claude/settings.json — "
            "Claude sessions won't auto-export to the session DB"
        ),
        fix_hint="studyloop doctor --fix  (merges a session-export Stop hook)",
        fix_auto=True,
    )


def _skill_path(tool: str):
    if link := installers.SESSION_MEMORY_SKILL_LINKS.get(tool):
        return link.target
    return installers.SESSION_MEMORY_SKILL_HUB


def _session_memory_skill_result(tool: str) -> CheckResult:
    from pathlib import Path

    path = Path(_skill_path(tool)).expanduser() / "SKILL.md"
    present = path.exists() and "name: studyloop-session-memory" in path.read_text(encoding="utf-8")
    return CheckResult(
        category="harness",
        name=f"session_memory_skill_{tool}",
        status="pass" if present else "warn",
        message=(
            f"{tool}: session-memory query skill installed"
            if present
            else f"{tool}: missing session-memory query skill at {path}"
        ),
        fix_hint="" if present else "studyloop doctor --fix  (installs agent skills)",
        fix_auto=not present,
    )


def _text_hook_result(tool: str, path, command: str) -> CheckResult:
    present = path.exists()
    text = path.read_text(encoding="utf-8") if present else ""
    present = present and installers._SESSION_HOOK_SENTINEL in text and command in text
    return CheckResult(
        category="harness",
        name=f"session_export_hook_{tool}",
        status="pass" if present else "warn",
        message=(
            f"{tool}: automatic session-export hook installed"
            if present
            else f"{tool}: missing automatic session-export hook at {path}"
        ),
        fix_hint="" if present else "studyloop doctor --fix  (installs session-end hook)",
        fix_auto=not present,
    )


def _kiro_hook_result() -> CheckResult:
    path = installers._kiro_agent_path()
    present = False
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stop = (data.get("hooks", {}) or {}).get("stop", []) or []
            present = any(
                "session-export --kiro-only" in str(hook.get("command", ""))
                for hook in stop
                if isinstance(hook, dict)
            )
        except (OSError, json.JSONDecodeError):
            present = False
    return CheckResult(
        category="harness",
        name="session_export_hook_kiro",
        status="pass" if present else "warn",
        message=(
            "kiro: automatic session-export stop hook installed in study-mentor agent"
            if present
            else "kiro: study-mentor agent has no automatic session-export stop hook"
        ),
        fix_hint="" if present else "studyloop doctor --fix  (reinstalls Kiro agent)",
        fix_auto=not present,
    )


def _codex_hook_result() -> CheckResult:
    path = installers._codex_hooks_path()
    present = False
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            groups = (data.get("hooks", {}) or {}).get("SessionEnd", []) or []
            present = any(
                installers._CODEX_HOOK_SENTINEL in str(hook.get("command", ""))
                for group in groups
                if isinstance(group, dict)
                for hook in group.get("hooks", [])
                if isinstance(hook, dict)
            )
        except (OSError, json.JSONDecodeError):
            present = False
    return CheckResult(
        category="harness",
        name="session_export_hook_codex",
        status="pass" if present else "warn",
        message=(
            "codex: automatic SessionEnd export hook installed"
            if present
            else f"codex: missing SessionEnd export hook in {path}"
        ),
        fix_hint="" if present else "studyloop doctor --fix  (merges Codex SessionEnd hook)",
        fix_auto=not present,
    )


def _executable_result(command: str) -> CheckResult:
    present = shutil.which(command) is not None
    purpose = {
        "session-query": "prior sessions cannot be queried",
        "session-export": "current sessions cannot be exported",
        "session-db-mcp": "session_search cannot be provided over MCP",
    }.get(command, "session-memory capability unavailable")
    return CheckResult(
        category="harness",
        name=f"session_memory_executable_{command}",
        status="pass" if present else "warn",
        message=f"{command}: installed" if present else f"{command}: not found on PATH; {purpose}",
        fix_hint="" if present else "studyloop install tools",
        fix_auto=not present,
    )


def check_harness_export() -> list[CheckResult]:
    """Verify detected harnesses have query skill + automatic export hook."""
    results: list[CheckResult] = [
        _executable_result("session-query"),
        _executable_result("session-export"),
        _executable_result("session-db-mcp"),
    ]
    detected = installers.detect_available_agent_tools()
    for tool in detected:
        results.append(_session_memory_skill_result(tool))
        if tool in installers._HARNESS_EXPORT:
            results.append(_steering_result(tool))
        if tool == "claude":
            results.append(_claude_hook_result())
        elif tool == "codex":
            results.append(_codex_hook_result())
        elif tool == "kiro":
            results.append(_kiro_hook_result())
        elif tool == "opencode":
            results.append(
                _text_hook_result(
                    tool,
                    installers._opencode_hook_path(),
                    "session-export --opencode-only",
                )
            )
        elif tool == "pi":
            results.append(
                _text_hook_result(
                    tool,
                    installers._pi_hook_path(),
                    '"--pi-only"',
                )
            )
    return results


def check_ontology_freshness() -> list[CheckResult]:
    """Report tier-1 ontology health: present, coverage, freshness, extraction version.

    Report-only (design: "New checkers cover ontology freshness..."; spec
    ``health-and-diagnostics`` "Ontology, concept-sidecar, and
    MCP-registration checks are classified report-only, never fatal") --
    every result here is ``pass``/``warn``/``info`` with ``fix_auto=False``,
    never ``fail``, and never contributes to doctor's exit code. The
    ontology is derived and never synced; a stale or absent ontology on one
    machine is recovered by ``session-maint ontology-rebuild``, not by
    anything doctor itself changes.
    """
    import importlib.util

    if importlib.util.find_spec("agent_session_tools") is None:
        return [
            CheckResult(
                "harness",
                "ontology_freshness",
                "info",
                "agent-session-tools not installed — ontology not checked",
                "studyloop install tools",
                fix_auto=False,
            )
        ]

    import sqlite3

    from studyloop.doctor.database import _get_sessions_db_path

    db_path = _get_sessions_db_path()
    if not db_path.exists():
        return [
            CheckResult(
                "harness",
                "ontology_freshness",
                "info",
                f"Sessions DB not found: {db_path} — ontology not checked",
                "Run any agent session tool to create it",
                fix_auto=False,
            )
        ]

    from agent_session_tools import ontology

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            status = ontology.ontology_status(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return [
            CheckResult(
                "harness",
                "ontology_freshness",
                "warn",
                f"Could not read ontology status: {exc}",
                "",
                fix_auto=False,
            )
        ]

    results: list[CheckResult] = []

    if status.missing_tables:
        results.append(
            CheckResult(
                "harness",
                "ontology_present",
                "warn",
                "Tier-1 ontology not yet built (missing tables: "
                f"{', '.join(status.missing_tables)})",
                "session-maint ontology-rebuild",
                fix_auto=False,
            )
        )
        return results
    results.append(
        CheckResult(
            "harness",
            "ontology_present",
            "pass",
            "Tier-1 ontology schema present",
            "",
            fix_auto=False,
        )
    )

    if status.coverage_ratio < 0.99:
        results.append(
            CheckResult(
                "harness",
                "ontology_coverage",
                "warn",
                f"Ontology session coverage {status.coverage_ratio:.2%} is below 99% "
                f"({status.missing_sessions} session(s) not covered)",
                "session-maint ontology-rebuild",
                fix_auto=False,
            )
        )
    else:
        results.append(
            CheckResult(
                "harness",
                "ontology_coverage",
                "pass",
                f"Ontology session coverage {status.coverage_ratio:.2%}",
                "",
                fix_auto=False,
            )
        )

    if not status.fresh:
        results.append(
            CheckResult(
                "harness",
                "ontology_freshness",
                "warn",
                "Ontology is stale relative to captured sessions "
                f"(completed_at={status.completed_at!r})",
                "session-maint ontology-rebuild",
                fix_auto=False,
            )
        )
    else:
        results.append(
            CheckResult(
                "harness",
                "ontology_freshness",
                "pass",
                f"Ontology is fresh (completed_at={status.completed_at})",
                "",
                fix_auto=False,
            )
        )

    if not status.extraction_version_matches:
        results.append(
            CheckResult(
                "harness",
                "ontology_extraction_version",
                "warn",
                "Ontology extraction version mismatch "
                f"(recorded={status.extraction_version!r}, "
                f"expected={ontology.EXTRACTION_VERSION!r})",
                "session-maint ontology-rebuild",
                fix_auto=False,
            )
        )
    else:
        results.append(
            CheckResult(
                "harness",
                "ontology_extraction_version",
                "pass",
                f"Ontology extraction version matches: {status.extraction_version}",
                "",
                fix_auto=False,
            )
        )

    return results
