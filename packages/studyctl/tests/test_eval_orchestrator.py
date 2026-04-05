"""Tests for the eval orchestrator — run_evaluation pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scenario(sid: str, name: str = "") -> object:
    from studyctl.eval.models import Scenario

    return Scenario(
        id=sid,
        name=name or sid,
        priority="normal",
        topic="Python",
        energy=5,
        prompt=f"Prompt for {sid}",
        elapsed_minutes=10,
        setup_prompts=[],
        heuristic_checks=[],
        rubric_weights={},
    )


def _passing_judge_result(scenario_id: str) -> object:
    from studyctl.eval.models import JudgeResult

    return JudgeResult(
        scenario_id=scenario_id,
        heuristic_pass=True,
        dimensions={"clarity": 4, "socratic_quality": 3},
        weights={"clarity": 1.0, "socratic_quality": 1.0},
    )


def _failing_judge_result(scenario_id: str) -> object:
    from studyctl.eval.models import JudgeResult

    return JudgeResult(
        scenario_id=scenario_id,
        heuristic_pass=False,
        dimensions={"clarity": 1},
        weights={"clarity": 1.0},
    )


def _make_target() -> MagicMock:
    target = MagicMock()
    target.name = "persona"
    target.run.return_value = "Mock response text"
    return target


def _make_reporter() -> MagicMock:
    reporter = MagicMock()
    return reporter


# ---------------------------------------------------------------------------
# Core pipeline tests
# ---------------------------------------------------------------------------


class TestRunEvaluationPipeline:
    def test_runs_all_scenarios_with_setup_teardown(self) -> None:
        """setup, run, teardown called exactly once per scenario."""
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario(f"s{i}") for i in range(3)]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()

        judge.score.side_effect = [_passing_judge_result(s.id) for s in scenarios]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert target.setup.call_count == 3
        assert target.run.call_count == 3
        assert target.teardown.call_count == 3

    def test_setup_receives_scenario(self) -> None:
        """setup() is called with the correct Scenario object."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("check-scenario")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, [scenario], reporter, agent="claude")

        target.setup.assert_called_once_with(scenario)

    def test_run_receives_scenario(self) -> None:
        """run() is called with the correct Scenario object."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("check-run")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, [scenario], reporter, agent="claude")

        target.run.assert_called_once_with(scenario)

    def test_judge_receives_response_from_target(self) -> None:
        """judge.score() receives the string returned by target.run()."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("check-judge")
        target = _make_target()
        target.run.return_value = "specific response text"
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, [scenario], reporter, agent="claude")

        judge.score.assert_called_once_with(scenario, "specific response text")


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------


class TestResultRecording:
    def test_heuristic_failure_recorded(self) -> None:
        """When judge returns heuristic_pass=False, that result is in the summary."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("heuristic-fail")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _failing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="claude")

        assert len(summary.results) == 1
        assert summary.results[0].heuristic_pass is False
        assert summary.results[0].scenario_id == "heuristic-fail"

    def test_timeout_recorded_on_exception(self) -> None:
        """When target.run() raises any exception, JudgeResult.timeout() is recorded."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("timeout-scenario")
        target = _make_target()
        target.run.side_effect = RuntimeError("connection lost")
        judge = MagicMock()
        reporter = _make_reporter()

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="claude")

        assert len(summary.results) == 1
        result = summary.results[0]
        assert result.scenario_id == "timeout-scenario"
        assert result.heuristic_pass is False
        assert result.raw_response == "TIMEOUT"
        assert result.passed is False

    def test_timeout_recorded_on_setup_exception(self) -> None:
        """When target.setup() raises, the scenario still gets a timeout result."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("setup-fail")
        target = _make_target()
        target.setup.side_effect = OSError("tmux not found")
        judge = MagicMock()
        reporter = _make_reporter()

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="claude")

        assert len(summary.results) == 1
        assert summary.results[0].raw_response == "TIMEOUT"

    def test_teardown_called_even_on_run_error(self) -> None:
        """teardown() executes regardless of whether run() raises."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("run-error")
        target = _make_target()
        target.run.side_effect = ValueError("bad state")
        judge = MagicMock()
        reporter = _make_reporter()

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, [scenario], reporter, agent="claude")

        target.teardown.assert_called_once()

    def test_teardown_called_even_on_judge_error(self) -> None:
        """teardown() executes even if judge.score() raises."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("judge-error")
        target = _make_target()
        judge = MagicMock()
        judge.score.side_effect = RuntimeError("LLM quota exceeded")
        reporter = _make_reporter()

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, [scenario], reporter, agent="claude")

        target.teardown.assert_called_once()

    def test_teardown_failure_does_not_abort_remaining_scenarios(self) -> None:
        """If teardown() raises, the next scenario still runs."""
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario("s1"), _make_scenario("s2")]
        target = _make_target()
        target.teardown.side_effect = OSError("cleanup failed")
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [
            _passing_judge_result("s1"),
            _passing_judge_result("s2"),
        ]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        # Both scenarios were attempted despite teardown failure
        assert len(summary.results) == 2


# ---------------------------------------------------------------------------
# EvalSummary fields
# ---------------------------------------------------------------------------


class TestEvalSummaryFields:
    def test_summary_has_correct_agent(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("s1")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="gemini")

        assert summary.agent == "gemini"

    def test_summary_has_persona_hash(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("s1")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(
                target,
                judge,
                [scenario],
                reporter,
                agent="claude",
                persona_hash="deadbeef",
            )

        assert summary.persona_hash == "deadbeef"

    def test_summary_commit_from_short_hash(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("s1")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="claude")

        assert summary.commit == "abc1234"

    def test_summary_timestamp_set(self) -> None:
        """timestamp is a non-empty ISO-format string."""
        from studyctl.eval.orchestrator import run_evaluation

        scenario = _make_scenario("s1")
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.return_value = _passing_judge_result(scenario.id)

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [scenario], reporter, agent="claude")

        assert summary.timestamp != ""
        # Should look like ISO format: YYYY-MM-DDTHH:MM:SS
        assert "T" in summary.timestamp

    def test_summary_results_count_matches_scenarios(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario(f"s{i}") for i in range(5)]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [_passing_judge_result(s.id) for s in scenarios]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert len(summary.results) == 5


# ---------------------------------------------------------------------------
# Reporter integration
# ---------------------------------------------------------------------------


class TestReporterIntegration:
    def test_reporter_record_called_once(self) -> None:
        """reporter.record() is called exactly once with the completed summary."""
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario("s1"), _make_scenario("s2")]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [_passing_judge_result(s.id) for s in scenarios]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        reporter.record.assert_called_once_with(summary)

    def test_reporter_called_after_all_scenarios(self) -> None:
        """reporter.record() is only called after ALL scenarios have been evaluated."""
        from studyctl.eval.orchestrator import run_evaluation

        call_order: list[str] = []

        scenarios = [_make_scenario("s1"), _make_scenario("s2")]
        target = _make_target()
        target.run.side_effect = lambda s: call_order.append(f"run:{s.id}") or "resp"

        judge = MagicMock()
        judge.score.side_effect = lambda s, r: (
            call_order.append(f"judge:{s.id}") or _passing_judge_result(s.id)
        )

        reporter = _make_reporter()
        reporter.record.side_effect = lambda _: call_order.append("record")

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert call_order.index("record") > call_order.index("judge:s2")


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------


class TestScoreAggregation:
    def test_avg_score_calculated_from_results(self) -> None:
        """Summary.avg_score is the mean of all JudgeResult weighted scores."""
        from studyctl.eval.models import JudgeResult
        from studyctl.eval.orchestrator import run_evaluation

        # s1: all 4s with weight 1.0 → 100%
        # s2: all 2s with weight 1.0 → 50%
        # avg = 75%
        result_s1 = JudgeResult(
            scenario_id="s1",
            heuristic_pass=True,
            dimensions={"clarity": 4},
            weights={"clarity": 1.0},
        )
        result_s2 = JudgeResult(
            scenario_id="s2",
            heuristic_pass=True,
            dimensions={"clarity": 2},
            weights={"clarity": 1.0},
        )

        scenarios = [_make_scenario("s1"), _make_scenario("s2")]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [result_s1, result_s2]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert summary.avg_score == 75.0

    def test_avg_score_empty_scenarios(self) -> None:
        """No scenarios → avg_score is 0.0."""
        from studyctl.eval.orchestrator import run_evaluation

        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, [], reporter, agent="claude")

        assert summary.avg_score == 0.0

    def test_all_passed_when_all_scenarios_pass(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario(f"s{i}") for i in range(3)]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [_passing_judge_result(s.id) for s in scenarios]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert summary.all_passed is True

    def test_all_passed_false_when_one_fails(self) -> None:
        from studyctl.eval.orchestrator import run_evaluation

        scenarios = [_make_scenario("pass"), _make_scenario("fail")]
        target = _make_target()
        judge = MagicMock()
        reporter = _make_reporter()
        judge.score.side_effect = [
            _passing_judge_result("pass"),
            _failing_judge_result("fail"),
        ]

        with patch("studyctl.eval.orchestrator.short_hash", return_value="abc1234"):
            summary = run_evaluation(target, judge, scenarios, reporter, agent="claude")

        assert summary.all_passed is False
