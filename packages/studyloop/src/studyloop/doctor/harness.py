"""Doctor checks for cross-harness session-export wiring (W4).

The session DB is StudyLoop's single source of truth for cross-harness
struggle tracking. For it to stay populated, each coding harness needs:

1. A steering-file mandate telling its agent to run ``session-export`` at
   session end (keyed on the ``studyloop:session-export-mandate`` sentinel).
2. (Claude only) a ``Stop`` hook in ``~/.claude/settings.json`` that runs
   ``session-export --claude-only`` automatically.

These checks warn (auto-fixable) when either is missing, so a machine that
has silently stopped exporting sessions is caught by ``studyloop doctor``.
"""

from __future__ import annotations

import json

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
            name="claude_stop_hook",
            status="pass",
            message="claude: session-export Stop hook registered",
            fix_hint="",
            fix_auto=False,
        )
    return CheckResult(
        category="harness",
        name="claude_stop_hook",
        status="warn",
        message=(
            "claude: no session-export Stop hook in ~/.claude/settings.json — "
            "Claude sessions won't auto-export to the session DB"
        ),
        fix_hint="studyloop doctor --fix  (merges a session-export Stop hook)",
        fix_auto=True,
    )


def check_harness_export() -> list[CheckResult]:
    """Verify each detected harness is wired to export sessions to the DB."""
    results: list[CheckResult] = []
    detected = installers.detect_available_agent_tools()
    for tool in detected:
        if tool in installers._HARNESS_EXPORT:
            results.append(_steering_result(tool))
    if "claude" in detected:
        results.append(_claude_hook_result())
    return results
