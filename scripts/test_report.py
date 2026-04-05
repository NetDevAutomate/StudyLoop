"""Tests for test_iterate.py — XML parsing, regression detection, report generation.

All fixtures inline (no conftest.py — pluggy conflict, see MEMORY.md).
Run: uv run pytest scripts/test_report.py -v
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Bootstrap: make test_iterate importable
sys.path.insert(0, str(Path(__file__).parent))
from studyctl.eval.targets.test_suite import (
    Outcome,
    TestKey,
    TestResult,
    build_iteration_result,
    parse_junit_xml,
)
from test_iterate import (
    _agent_breakdown_table,
    _build_json_output,
    detect_regressions,
    log_result,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test(
    name: str = "test_foo",
    agent: str = "claude",
    outcome: Outcome = "passed",
    duration: float = 0.5,
    message: str = "",
) -> TestResult:
    full_name = f"tests.TestMatrix::{name}[{agent}]"
    return TestResult(
        name=full_name,
        classname="tests.TestMatrix",
        outcome=outcome,
        duration=duration,
        message=message or ("" if outcome == "passed" else f"{agent} {name} fail"),
    )


def _make_iteration(
    iteration: int = 1,
    tests: list[TestResult] | None = None,
    commit: str = "abc1234",
) -> IterationResult:
    if tests is None:
        tests = [_make_test()]
    all_pass = all(t.outcome == "passed" for t in tests)
    return build_iteration_result(iteration, tests, exit_code=0 if all_pass else 1)


# ---------------------------------------------------------------------------
# JUnit XML parsing — bug fixes
# ---------------------------------------------------------------------------


JUNIT_EMPTY_TIME = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" tests="1">
        <testcase classname="tests" name="test_skip" time=""/>
      </testsuite>
    </testsuites>
""")

JUNIT_MALFORMED = "<?xml version='1.0'?><broken"

JUNIT_WITH_FAILURE = '<?xml version="1.0" encoding="utf-8"?>\n' + textwrap.dedent("""\
    <testsuites>
      <testsuite name="pytest" tests="2">
        <testcase classname="tests.TestMatrix" name="test_start[claude]" time="0.5"/>
        <testcase classname="tests.TestMatrix" name="test_topics[gemini]" time="0.4">
          <failure message="topics file missing">
    tests/test_matrix.py:45: in test_topics
      assert TOPICS_FILE.exists()
          </failure>
        </testcase>
      </testsuite>
    </testsuites>
""")


class TestParseJunitXml:
    def test_empty_time_attribute_does_not_crash(self, tmp_path: Path) -> None:
        """float('') bug — should default to 0.0, not raise ValueError."""
        xml = tmp_path / "result.xml"
        xml.write_text(JUNIT_EMPTY_TIME)
        results = parse_junit_xml(xml)
        assert len(results) == 1
        assert results[0].duration == 0.0

    def test_malformed_xml_returns_empty(self, tmp_path: Path) -> None:
        """ET.ParseError should be caught, not crash."""
        xml = tmp_path / "result.xml"
        xml.write_text(JUNIT_MALFORMED)
        results = parse_junit_xml(xml)
        assert results == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        results = parse_junit_xml(tmp_path / "nonexistent.xml")
        assert results == []

    def test_failure_parsed_with_traceback(self, tmp_path: Path) -> None:
        xml = tmp_path / "result.xml"
        xml.write_text(JUNIT_WITH_FAILURE)
        results = parse_junit_xml(xml)
        failed = [r for r in results if r.outcome == "failed"]
        assert len(failed) == 1
        assert "topics file missing" in failed[0].message
        assert "assert TOPICS_FILE" in failed[0].traceback


# ---------------------------------------------------------------------------
# TestResult properties
# ---------------------------------------------------------------------------


class TestTestResultProperties:
    def test_base_name_strips_agent(self) -> None:
        t = _make_test("test_01_start", "claude")
        assert t.base_name == "test_01_start"

    def test_agent_extracted(self) -> None:
        t = _make_test("test_01_start", "gemini")
        assert t.agent == "gemini"

    def test_unparametrized_name(self) -> None:
        t = TestResult(name="test_plain", classname="tests", outcome="passed", duration=0.1)
        assert t.base_name == "test_plain"
        assert t.agent is None


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


class TestDetectRegressions:
    def test_basic_regression(self) -> None:
        prev = [_make_test("test_01", "claude", "passed")]
        curr = [_make_test("test_01", "claude", "failed")]
        regressions, fixes = detect_regressions(prev, curr)
        assert len(regressions) == 1
        assert regressions[0] == TestKey(agent="claude", base_name="test_01")
        assert fixes == []

    def test_basic_fix(self) -> None:
        prev = [_make_test("test_01", "claude", "failed")]
        curr = [_make_test("test_01", "claude", "passed")]
        regressions, fixes = detect_regressions(prev, curr)
        assert regressions == []
        assert len(fixes) == 1

    def test_skipped_not_treated_as_regression(self) -> None:
        prev = [_make_test("test_01", "claude", "passed")]
        curr = [_make_test("test_01", "claude", "skipped")]
        regressions, fixes = detect_regressions(prev, curr)
        assert regressions == []
        assert fixes == []

    def test_empty_inputs(self) -> None:
        regressions, fixes = detect_regressions([], [])
        assert regressions == []
        assert fixes == []


# ---------------------------------------------------------------------------
# Per-agent breakdown table
# ---------------------------------------------------------------------------


class TestAgentBreakdownTable:
    def test_table_has_expected_agents(self) -> None:
        tests = [
            _make_test("test_01", "claude", "passed"),
            _make_test("test_01", "gemini", "failed"),
        ]
        table = _agent_breakdown_table(tests)
        assert "claude" in table
        assert "gemini" in table
        assert "PASS" in table
        assert "FAIL" in table

    def test_empty_tests_returns_empty(self) -> None:
        assert _agent_breakdown_table([]) == ""


# ---------------------------------------------------------------------------
# TSV persistence
# ---------------------------------------------------------------------------


class TestTsvPersistence:
    def test_log_result_creates_and_appends(self, tmp_path: Path, monkeypatch) -> None:
        import test_iterate as ti

        tsv = tmp_path / "results.tsv"
        monkeypatch.setattr(ti, "RESULTS_FILE", tsv)

        log_result(_make_iteration(iteration=1))
        log_result(_make_iteration(iteration=2))

        lines = tsv.read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 rows


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_has_expected_keys(self) -> None:
        tests = [_make_test("test_01", "claude", "passed")]
        results = [_make_iteration(tests=tests)]
        output = _build_json_output(results)
        assert "generated_at" in output
        assert "commit" in output
        assert "iterations" in output
        assert "latest" in output
        assert "regressions" in output
        assert "improvements" in output
        assert "failures" in output

    def test_json_per_agent_populated(self) -> None:
        tests = [
            _make_test("test_01", "claude", "passed"),
            _make_test("test_01", "gemini", "failed"),
        ]
        results = [_make_iteration(tests=tests)]
        output = _build_json_output(results)
        assert "claude" in output["latest"]["per_agent"]
        assert "gemini" in output["latest"]["per_agent"]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


class TestCliWiring:
    def test_help_exits_zero(self) -> None:
        import subprocess

        script = Path(__file__).parent / "test_iterate.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--json" in result.stdout
        assert "--max-iterations" in result.stdout
        assert "--progress" in result.stdout
