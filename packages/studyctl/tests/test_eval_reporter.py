"""Tests for eval git_ops and reporter modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# git_ops
# ---------------------------------------------------------------------------


class TestGitOps:
    def test_short_hash_returns_string(self) -> None:
        from studyctl.eval.git_ops import short_hash

        result = short_hash()
        assert isinstance(result, str)
        assert len(result) in (7, len("unknown"))

    def test_is_clean_returns_bool(self) -> None:
        from studyctl.eval.git_ops import is_clean

        result = is_clean()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# TSVReporter — header and append behaviour
# ---------------------------------------------------------------------------


def _make_summary(
    agent: str = "claude",
    persona_hash: str = "abc1234",
    commit: str = "deadb33f",
    timestamp: str = "2026-01-01T12:00:00",
    scenario_ids: list[str] | None = None,
) -> object:
    """Build a minimal EvalSummary with one JudgeResult per scenario_id."""
    from studyctl.eval.models import EvalSummary, JudgeResult

    ids = scenario_ids or ["confused-student"]
    results = [
        JudgeResult(
            scenario_id=sid,
            heuristic_pass=True,
            dimensions={
                "clarity": 4,
                "socratic_quality": 3,
                "emotional_safety": 4,
                "energy_adaptation": 3,
                "tool_usage": 2,
                "topic_focus": 4,
                "win_recognition": 3,
            },
            weights={
                "clarity": 1.5,
                "socratic_quality": 2.0,
                "emotional_safety": 1.5,
                "energy_adaptation": 1.0,
                "tool_usage": 1.0,
                "topic_focus": 1.5,
                "win_recognition": 1.0,
            },
        )
        for sid in ids
    ]
    return EvalSummary(
        agent=agent,
        persona_hash=persona_hash,
        commit=commit,
        results=results,
        timestamp=timestamp,
    )


class TestTSVReporterHeader:
    def test_tsv_writes_header_on_first_call(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        tsv_path = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv_path)
        summary = _make_summary()

        reporter.record(summary)

        lines = tsv_path.read_text().splitlines()
        assert lines[0].startswith("timestamp\t")
        assert "scenario_id" in lines[0]
        assert "weighted_score" in lines[0]

    def test_tsv_appends_without_duplicating_header(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        tsv_path = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv_path)
        summary = _make_summary()

        reporter.record(summary)
        reporter.record(summary)

        lines = tsv_path.read_text().splitlines()
        header_count = sum(1 for line in lines if line.startswith("timestamp\t"))
        assert header_count == 1

    def test_tsv_row_per_scenario(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        tsv_path = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv_path)
        summary = _make_summary(scenario_ids=["confused-student", "parking-lot", "hyperfocus"])

        reporter.record(summary)

        lines = tsv_path.read_text().splitlines()
        # 1 header + 3 data rows
        data_rows = [line for line in lines if not line.startswith("timestamp\t")]
        assert len(data_rows) == 3

    def test_tsv_contains_dimension_scores(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        tsv_path = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv_path)
        summary = _make_summary()

        reporter.record(summary)

        content = tsv_path.read_text()
        # All dimension columns should appear in the header
        for dim in [
            "clarity",
            "socratic_quality",
            "emotional_safety",
            "energy_adaptation",
            "tool_usage",
            "topic_focus",
            "win_recognition",
        ]:
            assert dim in content

        # The data row should contain the numeric scores
        lines = tsv_path.read_text().splitlines()
        data_row = lines[1]  # first data row after header
        assert "4" in data_row  # clarity score
        assert "2" in data_row  # tool_usage score


# ---------------------------------------------------------------------------
# TSVReporter — markdown report
# ---------------------------------------------------------------------------


class TestMarkdownReport:
    def test_markdown_contains_scenario_names(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        reporter = TSVReporter(tmp_path / "eval-results.tsv")
        summary = _make_summary(scenario_ids=["confused-student", "parking-lot"])

        md = reporter.generate_markdown(summary)

        assert "confused-student" in md
        assert "parking-lot" in md

    def test_markdown_contains_agent_and_hash(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        reporter = TSVReporter(tmp_path / "eval-results.tsv")
        summary = _make_summary(agent="gemini", persona_hash="f00dface")

        md = reporter.generate_markdown(summary)

        assert "gemini" in md
        assert "f00dface" in md

    def test_markdown_summary_stats(self, tmp_path: Path) -> None:
        from studyctl.eval.reporter import TSVReporter

        reporter = TSVReporter(tmp_path / "eval-results.tsv")
        summary = _make_summary(scenario_ids=["s1", "s2", "s3"])

        md = reporter.generate_markdown(summary)

        # Passed count should appear somewhere
        assert "3/3" in md or "3" in md
        # Average score line
        assert "Average score" in md or "avg" in md.lower()
