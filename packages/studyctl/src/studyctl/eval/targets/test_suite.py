"""Test-suite evaluation target: runs pytest and parses JUnit XML results."""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Literal

from studyctl.eval.git_ops import short_hash

PROJECT_DIR = Path(__file__).resolve().parents[5]  # up to repo root
STUDYCTL_PKG = PROJECT_DIR / "packages" / "studyctl"
DEFAULT_TEST_PATH = "tests/test_harness_matrix.py"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Outcome = Literal["passed", "failed", "error", "skipped"]

_PARAM_RE = re.compile(r"^(.+?)\[(.+)\]$")


@dataclass
class TestResult:
    """Single test outcome parsed from JUnit XML."""

    name: str
    classname: str
    outcome: Outcome
    duration: float
    message: str = ""
    traceback: str = ""

    @property
    def short_name(self) -> str:
        """Test name without the class prefix."""
        return self.name.rsplit("::", 1)[-1] if "::" in self.name else self.name

    @cached_property
    def _param_match(self) -> re.Match[str] | None:
        return _PARAM_RE.match(self.short_name)

    @cached_property
    def base_name(self) -> str:
        """Strip [agent] suffix: 'test_01_session_start[claude]' -> 'test_01_session_start'"""
        m = self._param_match
        return m.group(1) if m else self.short_name

    @cached_property
    def agent(self) -> str | None:
        """Extract parameter: 'test_01_session_start[claude]' -> 'claude'"""
        m = self._param_match
        return m.group(2) if m else None


@dataclass(frozen=True)
class TestKey:
    """Hashable key for set-based regression detection."""

    agent: str
    base_name: str


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
    all_tests: list[TestResult] = field(default_factory=list)

    @property
    def failures(self) -> list[TestResult]:
        return [t for t in self.all_tests if t.outcome in ("failed", "error")]

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

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        print(f"WARNING: JUnit XML is malformed ({exc}), treating as crash run")
        return []

    root = tree.getroot()
    results: list[TestResult] = []

    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            name = case.get("name", "")
            classname = case.get("classname", "")
            duration = float(case.get("time", "0") or "0")

            # Determine outcome
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                outcome = "failed"
                message = failure.get("message", "")
                tb = (failure.text or "").strip()
            elif error is not None:
                outcome = "error"
                message = error.get("message", "")
                tb = (error.text or "").strip()
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
        all_tests=test_results,
    )
