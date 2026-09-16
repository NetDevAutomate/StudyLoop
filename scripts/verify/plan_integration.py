"""Verify the plan integration and write the receipt (D-15, design §8).

"Definition of done is a receipt, not a feeling." This script runs a fixed
registry of checks — the full suites, lint, format, pyright, the named Bug A /
Bug B node ids, the architecture guard, the no-active golden, the real stdio
inventory and its in-process twin, the plan suites, the docs contract, the ten
protected files against their two bases, the ``rg`` invariants, the combined
Web+MCP journey alone and inside the ``-m integration`` run, the #14 browser
module under ``-m e2e``, the JS unit tests, ``openspec validate`` and ``mkdocs
--strict`` — and writes one JSON receipt with every command, exit status,
pytest node count and measured value:

    docs/architecture/plan-integration/receipts/verify-<short-sha>.json

Every check is required. A check that cannot run (missing executable, import
error) is recorded as a FAILURE with its error text, never as "not applicable";
an unexpected success (an ``rg`` zero-hit invariant that finds hits exits 0,
the opposite of its expected 1) is a failure too. The process exits 0 only when
every check met its expected exit status.

Run from the repo root (takes ~15-20 minutes; the full suites dominate):

    uv run --group dev python scripts/verify/plan_integration.py
    uv run --group dev python scripts/verify/plan_integration.py --list

The registry and the receipt writer are unit-tested in
``packages/studyloop/tests/test_verify_plan_integration_script.py`` with an
injected runner; the committed receipt is the real run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from studyloop.mcp.inventory import LEARNING_RECORD_TOOL, PLAN_TOOL_NAMES

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# --------------------------------------------------------------------------
# Constants the checks measure against
# --------------------------------------------------------------------------

#: The pre-#10 no-active-plan golden (T3.1), captured at 848f413b. The digest is
#: a sha256 of a committed test fixture, not a credential (also recorded in
#: tasks.md and the D-16 rubric receipt).
GOLDEN = "packages/studyloop/tests/golden/now_plan_no_active.json"
GOLDEN_SHA256 = (  # pragma: allowlist secret
    "ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0"  # pragma: allowlist secret
)

#: The production inventory: 23 original tools + the nine plan tools (review 3, F13).
PRODUCTION_TOOL_COUNT = 32
CORE_TOOLS = frozenset({"list_courses", "get_study_backlog", "end_session"})

#: Protected test files: byte-identical to their base since the programme began.
PROTECTED_EARLY_BASE = "3a4f6b01"
PROTECTED_EARLY = (
    "packages/studyloop/tests/test_web_plans.py",
    "packages/studyloop/tests/test_cli_plan.py",
    "packages/studyloop/tests/test_planning_evaluation.py",
)
# Moved 0a20a796 -> 1f304a5f on 2026-09-16: the harness-tier merge (issue #21,
# pi promoted to core on 5/5 evidence) legitimately changed ONE line of
# test_agent_launcher.py -- the release-order tuple pin. The guard caught it
# (verify-33e70f29.json, 28/29) and the diff was read before the base moved.
PROTECTED_LATE_BASE = "1f304a5f"
PROTECTED_LATE = (
    "packages/studyloop/tests/test_learning_decision.py",
    "packages/studyloop/tests/test_web_now.py",
    "packages/studyloop/tests/test_recap_mastery_voice.py",
    "packages/studyloop/tests/test_web_session_start_pty.py",
    "packages/studyloop/tests/test_web_session_start_acp.py",
    "packages/studyloop/tests/test_web_session_ws.py",
    "packages/studyloop/tests/test_agent_launcher.py",
)

TESTS = "packages/studyloop/tests"
SRC = "packages/studyloop/src/studyloop"
ADAPTER_DIRS = (f"{SRC}/cli", f"{SRC}/web/routes", f"{SRC}/mcp")

UV = ("uv", "run", "--group", "dev")
PYTEST = (*UV, "pytest", "-q", "-p", "no:cacheprovider")

RECEIPTS_DIR = "docs/architecture/plan-integration/receipts"

# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One required check: a name, a command (or an in-process function) and
    the exit status that means "passed"."""

    name: str
    command: list[str] | Callable[[Path], tuple[int, dict[str, Any]]]
    expected_exit: int = 0
    required: bool = True
    env: dict[str, str] = field(default_factory=dict)

    @property
    def display_command(self) -> list[str] | str:
        if callable(self.command):
            return f"python:{self.command.__name__}"
        return list(self.command)


def _pytest(*args: str) -> list[str]:
    return [*PYTEST, *args]


def _rg(*args: str) -> list[str]:
    return ["rg", "-n", *args]


def check_golden_sha(repo_root: Path) -> tuple[int, dict[str, Any]]:
    """The committed golden is byte-for-byte the file T3.1 captured."""
    path = repo_root / GOLDEN
    if not path.exists():
        return 1, {"path": GOLDEN, "error": "golden file missing"}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (0 if digest == GOLDEN_SHA256 else 1), {
        "path": GOLDEN,
        "sha256": digest,
        "expected": GOLDEN_SHA256,
    }


def check_inventory_in_process(repo_root: Path) -> tuple[int, dict[str, Any]]:
    """The in-process twin of the stdio inventory: exactly 32 unique names,
    the nine plan tools, ``record_plan_learning`` and the core names."""
    _ = repo_root
    from studyloop.mcp.server import mcp

    names = sorted(mcp._tool_manager._tools)
    problems: list[str] = []
    if len(names) != len(set(names)):
        problems.append("duplicate names")
    if len(names) != PRODUCTION_TOOL_COUNT:
        problems.append(f"expected {PRODUCTION_TOOL_COUNT} tools, got {len(names)}")
    missing_plan = sorted(set(PLAN_TOOL_NAMES) - set(names))
    if missing_plan:
        problems.append(f"plan tools missing: {missing_plan}")
    if LEARNING_RECORD_TOOL not in names:
        problems.append(f"{LEARNING_RECORD_TOOL} missing")
    missing_core = sorted(CORE_TOOLS - set(names))
    if missing_core:
        problems.append(f"core tools missing: {missing_core}")
    return (1 if problems else 0), {
        "count": len(names),
        "expected_count": PRODUCTION_TOOL_COUNT,
        "names": names,
        "plan_tools": list(PLAN_TOOL_NAMES),
        "problems": problems,
    }


def build_checks(repo_root: Path) -> list[Check]:
    """The registry. Order is the order the receipt reports and the run executes."""
    js_tests = sorted(
        str(p.relative_to(repo_root)) for p in (repo_root / TESTS / "js").glob("*.test.js")
    )
    return [
        # --- static quality -------------------------------------------------
        Check("ruff-check", [*UV, "ruff", "check", "."]),
        Check("ruff-format", [*UV, "ruff", "format", "--check", "."]),
        Check("pyright", [*UV, "pyright"]),
        # --- the two bugs the programme exists for (D-1, D-2) ---------------
        Check(
            "bug-a-readiness-gated-doors",
            _pytest(
                f"{TESTS}/test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan",
                f"{TESTS}/test_web_plans.py::test_markdown_replacement_refuses_an_unready_active_document",
                f"{TESTS}/test_plan_application.py::test_create_transition_replace_refusal_payload_is_identical",
                f"{TESTS}/test_plan_surface_parity.py::test_activation_refusal_is_identical_via_cli_and_web",
            ),
        ),
        Check(
            "bug-b-partial-recording-reported",
            _pytest(
                f"{TESTS}/test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning",
                f"{TESTS}/test_planning_evaluation.py::test_successful_checkpoint_db_write_adds_no_warning",
            ),
        ),
        # --- the seam's guard and the no-active contract (D-5, D-6) ----------
        Check("architecture-guard", _pytest(f"{TESTS}/test_architecture_plan_seam.py")),
        Check("golden-no-active-sha", check_golden_sha),
        Check(
            "golden-no-active-byte-identity",
            _pytest(
                f"{TESTS}/test_now_plan_guidance.py::test_no_active_plans_json_byte_identical_to_golden"
            ),
        ),
        # --- the MCP inventory, both transports (D-8, D-9) --------------------
        Check(
            "stdio-inventory",
            _pytest(f"{TESTS}/test_mcp_stdio_smoke.py", "-m", "integration"),
        ),
        Check("inventory-in-process", check_inventory_in_process),
        # --- the named plan suites (review 4, T6.2 list) ----------------------
        Check(
            "plan-suites",
            _pytest(
                f"{TESTS}/test_plan_application.py",
                f"{TESTS}/test_plan_application_mutations.py",
                f"{TESTS}/test_plan_guidance.py",
                f"{TESTS}/test_plan_intent_snapshots.py",
                f"{TESTS}/test_plan_surface_parity.py",
                f"{TESTS}/test_plan_record.py",
                f"{TESTS}/test_plan_recording_failures.py",
                f"{TESTS}/test_web_plans.py",
                f"{TESTS}/test_web_plans_seam.py",
                f"{TESTS}/test_cli_plan.py",
                f"{TESTS}/test_cli_plan_seam.py",
                f"{TESTS}/test_mcp_plan_tools.py",
                f"{TESTS}/test_mcp_plan_record_seam.py",
                f"{TESTS}/test_mcp_next_action.py",
                f"{TESTS}/test_now_plan_guidance.py",
                f"{TESTS}/test_session_start_purpose.py",
                f"{TESTS}/test_plan_architect_persona.py",
            ),
        ),
        Check("docs-contract", _pytest(f"{TESTS}/test_docs_plan_integration_contract.py")),
        # --- protected files: byte-identical to their bases -------------------
        Check(
            "protected-files-3a4f6b01",
            ["git", "diff", "--quiet", PROTECTED_EARLY_BASE, "--", *PROTECTED_EARLY],
        ),
        Check(
            "protected-files-late-base",
            ["git", "diff", "--quiet", PROTECTED_LATE_BASE, "--", *PROTECTED_LATE],
        ),
        # --- the rg invariants (design §8) -----------------------------------
        # "used by": rg exits 0 when it finds a match in the package.
        Check("rg-plan-application-cli", _rg("PlanApplication", f"{SRC}/cli")),
        Check("rg-plan-application-web-routes", _rg("PlanApplication", f"{SRC}/web/routes")),
        Check("rg-plan-application-mcp", _rg("PlanApplication", f"{SRC}/mcp")),
        # "zero": rg exits 1 when nothing matches — the desired state.
        Check(
            "rg-no-adapter-storage-imports",
            _rg(r"studyloop\.planning\.(store|index|authoring|evaluation)\b", *ADAPTER_DIRS),
            expected_exit=1,
        ),
        Check(
            "rg-no-adapter-storage-imports-from-package",
            _rg(
                r"from studyloop\.planning import .*\b(store|index|authoring|evaluation)\b",
                *ADAPTER_DIRS,
            ),
            expected_exit=1,
        ),
        Check(
            "rg-no-focus-literal-under-session-routes",
            _rg(r'build_canonical_persona\("focus"', f"{SRC}/web/routes/session"),
            expected_exit=1,
        ),
        # --- the journeys (T6.3, #14, #15 DoD) --------------------------------
        Check(
            "combined-journey",
            _pytest(f"{TESTS}/test_plan_journey_combined.py", "-m", "integration"),
        ),
        Check(
            "integration-combined",
            _pytest(
                f"{TESTS}/test_mcp_stdio_smoke.py",
                f"{TESTS}/test_plan_journey_combined.py",
                "-m",
                "integration",
            ),
        ),
        # The same two modules in the other file order: pytest collects in the
        # order given, and the #15 DoD is about ORDERING regressions, so one
        # order proves one order (council review 5, GPT F10).
        Check(
            "integration-combined-reverse",
            _pytest(
                f"{TESTS}/test_plan_journey_combined.py",
                f"{TESTS}/test_mcp_stdio_smoke.py",
                "-m",
                "integration",
            ),
        ),
        Check(
            "browser-journey-e2e",
            _pytest(f"{TESTS}/test_web_plan_architect_journey.py", "-m", "e2e"),
            env={"STUDYLOOP_E2E_TIMEOUT_SCALE": ""},
        ),
        Check("js-unit", ["node", "--test", *js_tests]),
        # --- specs and docs ----------------------------------------------------
        Check(
            "openspec-validate", ["openspec", "validate", "--specs", "--all", "--no-interactive"]
        ),
        Check(
            "mkdocs-strict",
            ["uv", "run", "--extra", "docs", "mkdocs", "build", "--strict", "-q"],
            env={"NO_MKDOCS_2_WARNING": "1"},
        ),
        # --- the full suites, last (they dominate the wall clock) -------------
        Check("full-suite-studyloop", _pytest(TESTS)),
        Check(
            "full-suite-agent-session-tools",
            _pytest("packages/agent-session-tools/tests"),
        ),
    ]


# --------------------------------------------------------------------------
# Running and recording
# --------------------------------------------------------------------------

_COUNT_WORDS = "passed|failed|skipped|deselected|errors?|warnings?|xfailed|xpassed|rerun"
#: The summary line, with (``=== 4 passed in 1.2s ===``) or without (``4 passed in
#: 1.2s`` — what ``-q`` prints under the studyloop package's own config) bars.
_SUMMARY_LINE = re.compile(
    rf"^(?:=+ )?(?P<body>(?:\d+ (?:{_COUNT_WORDS})(?:, )?)+|no tests ran) in [\d.]+s"
)
_COUNT = re.compile(rf"(\d+) ({_COUNT_WORDS})")


def parse_pytest_counts(output: str) -> dict[str, int]:
    """Node counts from pytest's final summary line (``N passed, M skipped in …``)."""
    for line in reversed(output.splitlines()):
        match = _SUMMARY_LINE.search(line.strip())
        if match:
            counts: dict[str, int] = {}
            for number, word in _COUNT.findall(match.group("body")):
                key = "errors" if word.startswith("error") else word
                counts[key] = int(number)
            return counts
    return {}


def run_check(check: Check, repo_root: Path) -> tuple[int | None, str, str | None]:
    """Run one check for real. Returns ``(exit_code, output, error)``; a check
    that could not start at all has ``exit_code None`` and an ``error``."""
    if callable(check.command):
        try:
            code, measured = check.command(repo_root)
        except Exception as exc:  # recorded in the receipt, never swallowed
            return None, "", f"{type(exc).__name__}: {exc}"
        return code, json.dumps(measured, sort_keys=True), None
    env = {**os.environ, **check.env}
    try:
        proc = subprocess.run(
            check.command,
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return None, "", f"FileNotFoundError: {exc}"
    except OSError as exc:
        return None, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout + proc.stderr, None


def _tail(output: str, lines: int = 12) -> list[str]:
    return [line for line in output.splitlines() if line.strip()][-lines:]


def run_and_write(
    checks: Sequence[Check],
    *,
    out: Path,
    runner: Callable[[Check], tuple[int | None, str, str | None]],
    tree: dict[str, Any],
    log: Callable[[str], None] | None = None,
) -> int:
    """Run every check through ``runner``, write the receipt, return the exit status."""
    say = log or (lambda line: print(line, file=sys.stderr))
    rows: list[dict[str, Any]] = []
    for check in checks:
        started = time.perf_counter()
        exit_code, output, error = runner(check)
        duration = round(time.perf_counter() - started, 1)
        ok = exit_code is not None and exit_code == check.expected_exit and error is None
        measured: dict[str, Any] | None = None
        if callable(check.command) and output:
            try:
                measured = json.loads(output)
            except json.JSONDecodeError:
                measured = None
        row: dict[str, Any] = {
            "name": check.name,
            "command": check.display_command,
            "expected_exit": check.expected_exit,
            "exit_code": exit_code,
            "ok": ok,
            "required": check.required,
            "duration_s": duration,
            "counts": parse_pytest_counts(output) if not callable(check.command) else {},
            "measured": measured,
            "error": error,
            "output_tail": [] if ok else _tail(output),
        }
        rows.append(row)
        status = " ok " if ok else "FAIL"
        detail = f"exit={exit_code} expected={check.expected_exit}"
        if row["counts"]:
            detail += " " + ", ".join(f"{v} {k}" for k, v in row["counts"].items())
        if error:
            detail += f" — {error}"
        say(f"[{status}] {check.name:<44} {duration:>7.1f}s  {detail}")

    failed = [row["name"] for row in rows if not row["ok"]]
    receipt = {
        "artefact": "plan-integration verification receipt (D-15, design §8)",
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tree": tree,
        "python": sys.version.split()[0],
        "ok": not failed,
        "summary": {"total": len(rows), "passed": len(rows) - len(failed), "failed": len(failed)},
        "failed_checks": failed,
        "checks": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    say(f"receipt: {out}  ok={receipt['ok']}  {receipt['summary']}")
    return 0 if not failed else 1


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()


def describe_tree(repo_root: Path) -> dict[str, Any]:
    return {
        "sha": _git(repo_root, "rev-parse", "--short", "HEAD"),
        "full_sha": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git(repo_root, "status", "--porcelain")),
    }


def default_receipt_path(repo_root: Path, short_sha: str) -> Path:
    return repo_root / RECEIPTS_DIR / f"verify-{short_sha}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=f"receipt path (default: {RECEIPTS_DIR}/verify-<short-sha>.json)",
    )
    parser.add_argument("--list", action="store_true", help="print the registry and exit")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    checks = build_checks(repo_root)
    if args.list:
        for check in checks:
            command = check.display_command
            shown = command if isinstance(command, str) else " ".join(command)
            print(f"{check.name:<44} expect exit {check.expected_exit}  {shown}")
        return 0

    tree = describe_tree(repo_root)
    out = args.out or default_receipt_path(repo_root, tree["sha"])
    print(f"verifying {tree['branch']}@{tree['sha']} (dirty={tree['dirty']})", file=sys.stderr)
    return run_and_write(
        checks, out=out, runner=lambda check: run_check(check, repo_root), tree=tree
    )


if __name__ == "__main__":
    raise SystemExit(main())
