#!/usr/bin/env python3
"""Autoresearch-style iterate runner for studyctl.

Runs the test matrix, parses results via JUnit XML, tracks iterations
in results.tsv, and generates structured failure reports.  Follows the
keep/discard pattern from https://github.com/karpathy/autoresearch.

Usage:
    uv run python scripts/test_iterate.py                        # single iteration, report
    uv run python scripts/test_iterate.py --max-iterations 5     # iterate up to 5 times
    uv run python scripts/test_iterate.py --agent claude         # single agent only
    uv run python scripts/test_iterate.py --test-path tests/     # custom test path
    uv run python scripts/test_iterate.py --no-git-check         # skip clean-tree check
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from studyctl.eval.git_ops import is_clean as git_is_clean
from studyctl.eval.targets.test_suite import (
    DEFAULT_TEST_PATH,
    PROJECT_DIR,
    STUDYCTL_PKG,
    IterationResult,
    TestKey,
    TestResult,
    build_iteration_result,
    parse_junit_xml,
    run_tests,
)

RESULTS_FILE = PROJECT_DIR / "results.tsv"
REPORT_DIR = PROJECT_DIR / "docs" / "reports"


# ---------------------------------------------------------------------------
# Results tracking (TSV)
# ---------------------------------------------------------------------------

TSV_HEADER = "iteration\ttimestamp\ttotal\tpassed\tfailed\tskipped\tduration_s\tcommit\tstatus\n"


def log_result(result: IterationResult) -> None:
    """Append an iteration result to results.tsv."""
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text(TSV_HEADER)

    line = (
        f"{result.iteration}\t"
        f"{result.timestamp}\t"
        f"{result.total}\t"
        f"{result.passed}\t"
        f"{result.failed}\t"
        f"{result.skipped}\t"
        f"{result.duration_s}\t"
        f"{result.commit}\t"
        f"{result.status}\n"
    )
    with RESULTS_FILE.open("a") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


def detect_regressions(
    prev_tests: list[TestResult],
    curr_tests: list[TestResult],
) -> tuple[list[TestKey], list[TestKey]]:
    """Compare two iterations' test outcomes. Returns (regressions, fixes).

    Skipped tests are excluded -- only passed<->failed/error transitions count.
    """
    prev_passing = {
        TestKey(t.agent or "", t.base_name) for t in prev_tests if t.outcome == "passed"
    }
    curr_failing = {
        TestKey(t.agent or "", t.base_name) for t in curr_tests if t.outcome in ("failed", "error")
    }
    prev_failing = {
        TestKey(t.agent or "", t.base_name) for t in prev_tests if t.outcome in ("failed", "error")
    }
    curr_passing = {
        TestKey(t.agent or "", t.base_name) for t in curr_tests if t.outcome == "passed"
    }

    regressions = sorted(prev_passing & curr_failing, key=lambda k: (k.base_name, k.agent))
    fixes = sorted(prev_failing & curr_passing, key=lambda k: (k.base_name, k.agent))
    return regressions, fixes


def _agent_breakdown_table(tests: list[TestResult]) -> str:
    """Build a per-agent x per-test markdown table from test results."""
    icons = {"passed": "PASS", "failed": "FAIL", "error": "ERR", "skipped": "SKIP"}

    agents_seen: list[str] = []
    tests_seen: list[str] = []
    grid: dict[tuple[str, str], str] = {}

    for t in tests:
        agent = t.agent or "__other__"
        base = t.base_name
        if agent not in agents_seen:
            agents_seen.append(agent)
        if base not in tests_seen:
            tests_seen.append(base)
        grid[(agent, base)] = icons.get(t.outcome, "?")

    if not agents_seen or not tests_seen:
        return ""

    header = "| Test | " + " | ".join(agents_seen) + " |"
    sep = "|------|" + "|".join(["------"] * len(agents_seen)) + "|"

    rows = [header, sep]
    for test in tests_seen:
        cells = [grid.get((agent, test), "-") for agent in agents_seen]
        rows.append(f"| `{test}` | " + " | ".join(cells) + " |")

    totals = []
    for agent in agents_seen:
        agent_tests = [grid.get((agent, t), "-") for t in tests_seen]
        passed = sum(1 for c in agent_tests if c == "PASS")
        totals.append(f"{passed}/{len(tests_seen)}")
    rows.append("| **Total** | " + " | ".join(totals) + " |")

    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Failure report
# ---------------------------------------------------------------------------


def _read_source_context(traceback_text: str) -> str:
    """Extract file paths and line numbers from a traceback, read surrounding source."""
    lines: list[str] = []
    for tb_line in traceback_text.splitlines():
        if ".py:" in tb_line and " in " in tb_line:
            parts = tb_line.strip().split(":")
            if len(parts) >= 2:
                filepath = parts[0].strip()
                try:
                    lineno = int(parts[1])
                except ValueError:
                    continue

                candidates = [
                    Path(filepath),
                    PROJECT_DIR / filepath,
                    STUDYCTL_PKG / filepath,
                ]
                for candidate in candidates:
                    if candidate.exists():
                        try:
                            src_lines = candidate.read_text().splitlines()
                            start = max(0, lineno - 5)
                            end = min(len(src_lines), lineno + 5)
                            snippet = "\n".join(
                                f"{'>' if i + 1 == lineno else ' '} {i + 1:4d} | {src_lines[i]}"
                                for i in range(start, end)
                            )
                            lines.append(
                                f"\n**{candidate.relative_to(PROJECT_DIR)}:{lineno}**\n```python\n{snippet}\n```"
                            )
                        except OSError:
                            pass
                        break
    return "\n".join(lines) if lines else ""


def generate_report(results: list[IterationResult]) -> str:
    """Generate a markdown failure/regression report."""
    now = datetime.now(UTC).strftime("%Y-%m-%d")
    latest = results[-1] if results else None

    lines: list[str] = [
        f"# Iterate Report -- {now}",
        "",
        "## Summary",
        f"- **Iterations**: {len(results)}",
    ]

    if latest:
        lines.extend(
            [
                f"- **Tests**: {latest.total} total, {latest.passed} passed, "
                f"{latest.failed} failed, {latest.skipped} skipped",
                f"- **Duration**: {latest.duration_s}s",
                f"- **Status**: {latest.status}",
                f"- **Commit**: `{latest.commit}`",
            ]
        )

    if len(results) > 1:
        lines.extend(
            [
                "",
                "## Iteration History",
                "",
                "| # | Passed | Failed | Duration | Status | Commit |",
                "|---|--------|--------|----------|--------|--------|",
            ]
        )
        for r in results:
            lines.append(
                f"| {r.iteration} | {r.passed}/{r.total} | {r.failed} "
                f"| {r.duration_s}s | {r.status} | `{r.commit}` |"
            )

    # Per-agent breakdown
    if latest and latest.all_tests:
        table = _agent_breakdown_table(latest.all_tests)
        if table:
            lines.extend(["", "## Per-Agent Breakdown", "", table])

    # Regression / improvement detection
    if len(results) >= 2 and latest is not None:
        prev = results[-2]
        regressions, fixes = detect_regressions(prev.all_tests, latest.all_tests)
        if regressions:
            lines.extend(["", "## Regressions", ""])
            for key in regressions:
                agent_label = f" [{key.agent}]" if key.agent else ""
                lines.append(f"- `{key.base_name}`{agent_label} — was passing, now failing")
        if fixes:
            lines.extend(["", "## Fixed", ""])
            for key in fixes:
                agent_label = f" [{key.agent}]" if key.agent else ""
                lines.append(f"- `{key.base_name}`{agent_label} — was failing, now passing")

    # Failure details
    if latest and latest.failures:
        lines.extend(["", "## Failures", ""])
        for i, fail in enumerate(latest.failures, 1):
            lines.extend(
                [
                    f"### {i}. `{fail.short_name}`",
                    "",
                    f"**Class**: `{fail.classname}`",
                    f"**Message**: {fail.message}",
                    "",
                ]
            )
            if fail.traceback:
                lines.extend(
                    [
                        "<details><summary>Full traceback</summary>",
                        "",
                        "```",
                        fail.traceback.strip(),
                        "```",
                        "",
                        "</details>",
                    ]
                )
                source = _read_source_context(fail.traceback)
                if source:
                    lines.extend(["", "**Source context:**", source])
            lines.append("")

    elif latest and latest.all_passed:
        lines.extend(["", "## Result", "", f"All {latest.total} tests passed."])

    return "\n".join(lines)


def _build_json_output(results: list[IterationResult]) -> dict:
    """Build structured JSON output for agent consumption."""
    latest = results[-1] if results else None

    per_agent: dict[str, dict[str, int]] = {}
    if latest:
        for t in latest.all_tests:
            agent = t.agent or "__other__"
            if agent not in per_agent:
                per_agent[agent] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
            per_agent[agent][t.outcome] = per_agent[agent].get(t.outcome, 0) + 1

    regressions_list: list[dict[str, str]] = []
    improvements_list: list[dict[str, str]] = []
    if len(results) >= 2 and latest is not None:
        regs, fixes = detect_regressions(results[-2].all_tests, latest.all_tests)
        regressions_list = [{"agent": k.agent, "test": k.base_name} for k in regs]
        improvements_list = [{"agent": k.agent, "test": k.base_name} for k in fixes]

    failures_list: list[dict[str, str]] = []
    if latest:
        for f in latest.failures:
            failures_list.append(
                {
                    "agent": f.agent or "",
                    "test": f.base_name,
                    "message": f.message,
                    "traceback": f.traceback,
                }
            )

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": latest.commit if latest else "",
        "iterations": [
            {
                "iteration": r.iteration,
                "total": r.total,
                "passed": r.passed,
                "failed": r.failed,
                "skipped": r.skipped,
                "status": r.status,
            }
            for r in results
        ],
        "latest": {
            "total": latest.total if latest else 0,
            "passed": latest.passed if latest else 0,
            "failed": latest.failed if latest else 0,
            "per_agent": per_agent,
        },
        "regressions": regressions_list,
        "improvements": improvements_list,
        "failures": failures_list,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_tsv_rows() -> list[dict[str, str]]:
    """Read results.tsv into a list of dicts keyed by header names."""
    if not RESULTS_FILE.exists():
        return []
    lines = RESULTS_FILE.read_text().strip().splitlines()
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) >= len(header):
            rows.append(dict(zip(header, cols, strict=False)))
    return rows


def show_progress(*, as_json: bool = False) -> int:
    """Display results.tsv history as a formatted table (or JSON)."""
    rows = _parse_tsv_rows()
    if not rows:
        if not RESULTS_FILE.exists():
            print("No results.tsv found. Run an iteration first.")
            return 1
        print("No iteration results recorded yet.")
        return 0

    if as_json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"\n  {'Autoresearch Iterate History':^58}")
    print(f"  {'=' * 58}")
    print(f"  {'#':>3}  {'Timestamp':<20} {'Pass':>6} {'Fail':>6} {'Time':>7}  {'Status':<10}")
    print(f"  {'-' * 58}")

    for row in rows:
        iteration = row.get("iteration", "?")
        ts = row.get("timestamp", "")
        timestamp = ts[11:19] if len(ts) > 11 else ts
        total = row.get("total", "?")
        passed = row.get("passed", "?")
        failed = row.get("failed", "?")
        duration = row.get("duration_s", "?")
        status = row.get("status", "?")

        status_icon = {"complete": "+", "partial": "~", "crash": "!"}
        icon = status_icon.get(status, "?")

        print(
            f"  {iteration:>3}  {timestamp:<20} "
            f"{passed:>3}/{total:<3} {failed:>4}   "
            f"{duration:>5}s  {icon} {status}"
        )

    print(f"  {'=' * 58}")
    print(f"  Source: {RESULTS_FILE.relative_to(PROJECT_DIR)}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autoresearch-style iterate runner for studyctl",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help="Maximum iterations to run (default: 1)",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Test a single agent only (e.g. 'claude')",
    )
    parser.add_argument(
        "--test-path",
        type=str,
        default=DEFAULT_TEST_PATH,
        help=f"Path to test file relative to studyctl package (default: {DEFAULT_TEST_PATH})",
    )
    parser.add_argument(
        "--no-git-check",
        action="store_true",
        help="Skip the clean working tree check",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write a markdown report to docs/reports/",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show results.tsv history and exit (no tests run)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (works with --progress and main run)",
    )
    args = parser.parse_args()

    # Show progress history
    if args.progress:
        return show_progress(as_json=args.json)

    # Max iterations safety cap
    if args.max_iterations > 10:
        print("ERROR: --max-iterations capped at 10 to prevent runaway CI costs.")
        return 1

    # Git safety check
    if not args.no_git_check and not git_is_clean():
        print("ERROR: Working tree is not clean. Commit or stash changes first.")
        print("       Use --no-git-check to skip this check.")
        return 1

    all_results: list[IterationResult] = []

    for i in range(1, args.max_iterations + 1):
        print(f"\n{'=' * 60}")
        print(f"  Iteration {i}/{args.max_iterations}")
        print(f"{'=' * 60}\n")

        xml_path, exit_code = run_tests(
            test_path=args.test_path,
            agent=args.agent,
        )

        test_results = parse_junit_xml(xml_path)
        result = build_iteration_result(i, test_results, exit_code)
        all_results.append(result)

        log_result(result)

        print(
            f"\n  {result.passed}/{result.total} passed, "
            f"{result.failed} failed, {result.skipped} skipped ({result.duration_s}s)"
        )
        print(f"  Status: {result.status} | Commit: {result.commit}")

        if result.all_passed:
            print(f"\n  All {result.total} tests passed!")
            break

        print(f"\n  Failures ({result.failed + result.errored}):")
        for fail in result.failures:
            print(f"    - {fail.short_name}: {fail.message[:100]}")

        if i < args.max_iterations:
            print("\n  Continuing to next iteration...")

    # Clean up XML artifact
    xml_artifact = PROJECT_DIR / ".pytest-junit.xml"
    if xml_artifact.exists():
        xml_artifact.unlink()

    # Generate report
    report = generate_report(all_results)

    if args.json:
        print(json.dumps(_build_json_output(all_results), indent=2))
    elif args.report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).strftime("%Y-%m-%d")
        report_path = REPORT_DIR / f"{now}-iterate-report.md"
        report_path.write_text(report)
        print(f"\n  Report: {report_path.relative_to(PROJECT_DIR)}")
    else:
        print(f"\n{'=' * 60}")
        print(report)

    if not args.json:
        print(f"\n  Results: {RESULTS_FILE.relative_to(PROJECT_DIR)}")

    final = all_results[-1] if all_results else None
    return 0 if final and final.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
