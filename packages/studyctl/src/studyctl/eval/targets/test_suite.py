"""Test-suite evaluation target: runs pytest and parses JUnit XML results."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from studyctl.eval.git_ops import short_hash

PROJECT_DIR = Path(__file__).resolve().parents[5]  # up to repo root
STUDYCTL_PKG = PROJECT_DIR / "packages" / "studyctl"
DEFAULT_TEST_PATH = "tests/test_harness_matrix.py"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """Single test outcome parsed from JUnit XML."""

    name: str
    classname: str
    outcome: str  # passed, failed, error, skipped
    duration: float
    message: str = ""
    traceback: str = ""

    @property
    def short_name(self) -> str:
        """Test name without the class prefix."""
        return self.name.rsplit("::", 1)[-1] if "::" in self.name else self.name


@dataclass
class IterationResult:
    """Aggregate result of one test run."""

    iteration: int
    timestamp: str
    total: int
    passed: int
    failed: int
    skipped: int
    errored: int
    duration_s: float
    commit: str
    status: str  # complete, partial, crash
    failures: list[TestResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errored == 0


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


def run_tests(
    test_path: str = DEFAULT_TEST_PATH,
    agent: str | None = None,
) -> tuple[Path, int]:
    """Run pytest with JUnit XML output. Returns (xml_path, exit_code)."""
    xml_path = PROJECT_DIR / ".pytest-junit.xml"

    cmd = [
        "uv",
        "run",
        "pytest",
        str(STUDYCTL_PKG / test_path),
        f"--junitxml={xml_path}",
        "--tb=long",
        "-v",
    ]
    if agent:
        cmd.extend(["-k", agent])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
        timeout=600,
    )

    return xml_path, result.returncode


# ---------------------------------------------------------------------------
# JUnit XML parsing
# ---------------------------------------------------------------------------


def parse_junit_xml(xml_path: Path) -> list[TestResult]:
    """Parse a JUnit XML file into TestResult objects."""
    if not xml_path.exists():
        return []

    tree = ET.parse(xml_path)
    root = tree.getroot()
    results: list[TestResult] = []

    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            name = case.get("name", "")
            classname = case.get("classname", "")
            duration = float(case.get("time", "0"))

            # Determine outcome
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                outcome = "failed"
                message = failure.get("message", "")
                tb = failure.text or ""
            elif error is not None:
                outcome = "error"
                message = error.get("message", "")
                tb = error.text or ""
            elif skipped is not None:
                outcome = "skipped"
                message = skipped.get("message", "")
                tb = ""
            else:
                outcome = "passed"
                message = ""
                tb = ""

            results.append(
                TestResult(
                    name=f"{classname}::{name}" if classname else name,
                    classname=classname,
                    outcome=outcome,
                    duration=duration,
                    message=message,
                    traceback=tb,
                )
            )

    return results


def build_iteration_result(
    iteration: int,
    test_results: list[TestResult],
    exit_code: int,
) -> IterationResult:
    """Aggregate individual test results into an IterationResult."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    passed = sum(1 for t in test_results if t.outcome == "passed")
    failed = sum(1 for t in test_results if t.outcome == "failed")
    errored = sum(1 for t in test_results if t.outcome == "error")
    skipped = sum(1 for t in test_results if t.outcome == "skipped")
    total_duration = sum(t.duration for t in test_results)

    failures = [t for t in test_results if t.outcome in ("failed", "error")]

    if not test_results and exit_code != 0:
        status = "crash"
    elif failed == 0 and errored == 0:
        status = "complete"
    else:
        status = "partial"

    return IterationResult(
        iteration=iteration,
        timestamp=now,
        total=len(test_results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        errored=errored,
        duration_s=round(total_duration, 1),
        commit=short_hash(),
        status=status,
        failures=failures,
    )
