"""Tests for eval models, scenario loader, and study.yaml."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


class TestLoadScenarios:
    def test_load_scenarios_from_yaml(self, tmp_path: Path) -> None:
        from studyctl.eval.scenarios import load_scenarios

        yaml_content = textwrap.dedent("""\
            scenarios:
              - id: test-basic
                name: Basic Test
                priority: normal
                topic: Python
                energy: 5
                elapsed_minutes: 10
                prompt: |
                  Tell me about Python.
                heuristic_checks: [references_topic]
                rubric_weights: {topic_focus: 1.5}
        """)
        f = tmp_path / "test.yaml"
        f.write_text(yaml_content)

        scenarios = load_scenarios(f)

        assert len(scenarios) == 1
        s = scenarios[0]
        assert s.id == "test-basic"
        assert s.name == "Basic Test"
        assert s.priority == "normal"
        assert s.topic == "Python"
        assert s.energy == 5
        assert s.elapsed_minutes == 10
        assert "Python" in s.prompt
        assert s.heuristic_checks == ["references_topic"]
        assert s.rubric_weights == {"topic_focus": 1.5}

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        from studyctl.eval.scenarios import load_scenarios

        with pytest.raises(FileNotFoundError):
            load_scenarios(tmp_path / "nonexistent.yaml")

    def test_scenario_missing_required_field_raises(self, tmp_path: Path) -> None:
        from studyctl.eval.scenarios import load_scenarios

        yaml_content = textwrap.dedent("""\
            scenarios:
              - id: incomplete
                name: Missing Fields
                topic: Python
                energy: 5
        """)
        # Missing required 'prompt' field
        f = tmp_path / "incomplete.yaml"
        f.write_text(yaml_content)

        with pytest.raises(ValueError, match="prompt"):
            load_scenarios(f)

    def test_scenario_defaults_applied(self, tmp_path: Path) -> None:
        """elapsed_minutes, setup_prompts, heuristic_checks, rubric_weights have defaults."""
        from studyctl.eval.scenarios import load_scenarios

        yaml_content = textwrap.dedent("""\
            scenarios:
              - id: minimal
                name: Minimal
                priority: normal
                topic: Python
                energy: 5
                prompt: Hello
        """)
        f = tmp_path / "minimal.yaml"
        f.write_text(yaml_content)

        scenarios = load_scenarios(f)
        s = scenarios[0]
        assert s.elapsed_minutes == 10
        assert s.setup_prompts == []
        assert s.heuristic_checks == []
        assert s.rubric_weights == {}

    def test_load_multiple_scenarios(self, tmp_path: Path) -> None:
        from studyctl.eval.scenarios import load_scenarios

        yaml_content = textwrap.dedent("""\
            scenarios:
              - id: first
                name: First
                priority: critical
                topic: Python
                energy: 3
                prompt: First prompt
              - id: second
                name: Second
                priority: high
                topic: Python
                energy: 7
                prompt: Second prompt
        """)
        f = tmp_path / "multi.yaml"
        f.write_text(yaml_content)

        scenarios = load_scenarios(f)
        assert len(scenarios) == 2
        assert scenarios[0].id == "first"
        assert scenarios[1].id == "second"


# ---------------------------------------------------------------------------
# Builtin scenarios
# ---------------------------------------------------------------------------


class TestBuiltinScenarios:
    def test_builtin_scenarios_path_exists(self) -> None:
        from studyctl.eval.scenarios import builtin_scenarios_path

        path = builtin_scenarios_path()
        assert path.exists(), f"study.yaml not found at {path}"
        assert path.name == "study.yaml"

    def test_load_builtin_scenarios(self) -> None:
        from studyctl.eval.scenarios import builtin_scenarios_path, load_scenarios

        scenarios = load_scenarios(builtin_scenarios_path())
        assert len(scenarios) == 7

        expected_ids = {
            "confused-student",
            "parking-lot",
            "hyperfocus",
            "win-recognition",
            "wrong-answer",
            "low-energy",
            "deep-dive",
        }
        actual_ids = {s.id for s in scenarios}
        assert actual_ids == expected_ids

    def test_builtin_critical_scenarios(self) -> None:
        from studyctl.eval.scenarios import builtin_scenarios_path, load_scenarios

        scenarios = load_scenarios(builtin_scenarios_path())
        critical = [s for s in scenarios if s.priority == "critical"]
        assert len(critical) == 4

    def test_builtin_scenarios_have_heuristic_checks(self) -> None:
        """All non-deep-dive scenarios define at least one heuristic check."""
        from studyctl.eval.scenarios import builtin_scenarios_path, load_scenarios

        scenarios = load_scenarios(builtin_scenarios_path())
        for s in scenarios:
            if s.id != "deep-dive":
                assert len(s.heuristic_checks) > 0, f"{s.id} missing heuristic_checks"


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------


class TestJudgeResult:
    def test_weighted_score_calculation(self) -> None:
        """(3*1.0 + 4*2.0) / (4*1.0 + 4*2.0) * 100 == 91.67"""
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"dim_a": 3, "dim_b": 4},
            weights={"dim_a": 1.0, "dim_b": 2.0},
        )
        assert abs(result.weighted_score - 91.6667) < 0.01

    def test_equal_weights_score(self) -> None:
        """All 4s with equal weights → 100%."""
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"a": 4, "b": 4},
            weights={"a": 1.0, "b": 1.0},
        )
        assert result.weighted_score == 100.0

    def test_heuristic_fail_scores_zero(self) -> None:
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=False,
            dimensions={"a": 4, "b": 4},
            weights={"a": 1.0, "b": 1.0},
        )
        assert result.weighted_score == 0.0

    def test_empty_dimensions_scores_zero(self) -> None:
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={},
            weights={},
        )
        assert result.weighted_score == 0.0

    def test_passed_property_above_threshold(self) -> None:
        """75% passes (>= 70%)."""
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"a": 3},
            weights={"a": 1.0},
        )
        # 3/4 * 100 = 75.0
        assert result.weighted_score == 75.0
        assert result.passed is True

    def test_passed_property_below_threshold(self) -> None:
        """50% fails (< 70%)."""
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"a": 2},
            weights={"a": 1.0},
        )
        # 2/4 * 100 = 50.0
        assert result.weighted_score == 50.0
        assert result.passed is False

    def test_passed_requires_heuristic_pass(self) -> None:
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=False,
            dimensions={"a": 4},
            weights={"a": 1.0},
        )
        assert result.passed is False

    def test_timeout_factory(self) -> None:
        from studyctl.eval.models import JudgeResult

        result = JudgeResult.timeout("scenario-xyz")
        assert result.scenario_id == "scenario-xyz"
        assert result.heuristic_pass is False
        assert result.dimensions == {}
        assert result.weights == {}
        assert result.raw_response == "TIMEOUT"
        assert result.passed is False

    def test_missing_weight_defaults_to_one(self) -> None:
        """Dimension without an explicit weight defaults to 1.0."""
        from studyctl.eval.models import JudgeResult

        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"a": 4},
            weights={},  # no weight for 'a' — should default to 1.0
        )
        assert result.weighted_score == 100.0


# ---------------------------------------------------------------------------
# EvalSummary
# ---------------------------------------------------------------------------


class TestEvalSummary:
    def test_avg_score_calculation(self) -> None:
        from studyctl.eval.models import EvalSummary, JudgeResult

        results = [
            JudgeResult(
                scenario_id="s1",
                heuristic_pass=True,
                dimensions={"a": 4},
                weights={"a": 1.0},
            ),
            JudgeResult(
                scenario_id="s2",
                heuristic_pass=True,
                dimensions={"a": 2},
                weights={"a": 1.0},
            ),
        ]
        summary = EvalSummary(
            agent="test-agent",
            persona_hash="abc123",
            commit="deadbeef",
            results=results,
        )
        # s1: 100%, s2: 50% → avg 75%
        assert summary.avg_score == 75.0

    def test_avg_score_empty_results(self) -> None:
        from studyctl.eval.models import EvalSummary

        summary = EvalSummary(
            agent="test-agent",
            persona_hash="abc123",
            commit="deadbeef",
            results=[],
        )
        assert summary.avg_score == 0.0

    def test_all_passed_true(self) -> None:
        from studyctl.eval.models import EvalSummary, JudgeResult

        results = [
            JudgeResult(
                scenario_id="s1",
                heuristic_pass=True,
                dimensions={"a": 4},
                weights={"a": 1.0},
            ),
            JudgeResult(
                scenario_id="s2",
                heuristic_pass=True,
                dimensions={"a": 3},
                weights={"a": 1.0},
            ),
        ]
        summary = EvalSummary(
            agent="agent",
            persona_hash="hash",
            commit="commit",
            results=results,
        )
        assert summary.all_passed is True

    def test_all_passed_false_when_any_fails(self) -> None:
        from studyctl.eval.models import EvalSummary, JudgeResult

        results = [
            JudgeResult(
                scenario_id="s1",
                heuristic_pass=True,
                dimensions={"a": 4},
                weights={"a": 1.0},
            ),
            JudgeResult(
                scenario_id="s2",
                heuristic_pass=False,
                dimensions={"a": 4},
                weights={"a": 1.0},
            ),
        ]
        summary = EvalSummary(
            agent="agent",
            persona_hash="hash",
            commit="commit",
            results=results,
        )
        assert summary.all_passed is False

    def test_timestamp_defaults_empty(self) -> None:
        from studyctl.eval.models import EvalSummary

        summary = EvalSummary(
            agent="agent",
            persona_hash="hash",
            commit="commit",
            results=[],
        )
        assert summary.timestamp == ""


# ---------------------------------------------------------------------------
# HeuristicResult
# ---------------------------------------------------------------------------


class TestHeuristicResult:
    def test_create_passed(self) -> None:
        from studyctl.eval.models import HeuristicResult

        r = HeuristicResult(
            passed=True,
            checks={"contains_question": True, "no_rsd_triggers": True},
        )
        assert r.passed is True
        assert r.checks["contains_question"] is True

    def test_create_with_messages(self) -> None:
        from studyctl.eval.models import HeuristicResult

        r = HeuristicResult(
            passed=False,
            checks={"references_topic": False},
            messages=["Response does not mention the topic"],
        )
        assert r.passed is False
        assert len(r.messages) == 1

    def test_messages_default_empty(self) -> None:
        from studyctl.eval.models import HeuristicResult

        r = HeuristicResult(passed=True, checks={})
        assert r.messages == []
