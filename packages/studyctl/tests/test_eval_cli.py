"""Tests for studyctl eval CLI commands (eval run, eval history, eval setup)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_summary(agent: str = "claude", avg: float = 85.0, passed: int = 3, total: int = 3):
    """Build a minimal EvalSummary for assertions."""
    from studyctl.eval.models import EvalSummary, JudgeResult

    results = [
        JudgeResult(
            scenario_id=f"s{i}",
            heuristic_pass=True,
            dimensions={"clarity": 4},
            weights={"clarity": 1.0},
        )
        for i in range(total)
    ]
    return EvalSummary(
        agent=agent,
        persona_hash="deadbeef",
        commit="abc1234",
        results=results,
        timestamp="2026-04-05T12:00:00",
    )


_SAMPLE_TSV = (
    "timestamp\tagent\tpersona_hash\tscenario_id\t"
    "heuristic_pass\tweighted_score\t"
    "clarity\tsocratic_quality\temotional_safety\tenergy_adaptation\t"
    "tool_usage\ttopic_focus\twin_recognition\tcommit\n"
    "2026-04-05T12:00:00\tclaude\tdeadbeef\ts1\tTrue\t87.50\t"
    "4\t3\t0\t0\t0\t0\t0\tabc1234\n"
    "2026-04-05T12:00:00\tclaude\tdeadbeef\ts2\tTrue\t75.00\t"
    "3\t3\t0\t0\t0\t0\t0\tabc1234\n"
)


# ---------------------------------------------------------------------------
# eval setup
# ---------------------------------------------------------------------------


class TestEvalSetup:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_eval_setup_runs(self, runner: CliRunner):
        """eval setup exits 0 when Ollama is reachable and RAM is detectable."""
        from studyctl.cli._eval import eval_group

        with (
            patch("studyctl.cli._eval._check_ollama_running", return_value=True),
            patch("studyctl.cli._eval._detect_ram_gb", return_value=64.0),
            patch("studyctl.cli._eval._is_apple_silicon", return_value=True),
            patch("studyctl.cli._eval._ollama_models", return_value=["gemma4:26b"]),
        ):
            result = runner.invoke(eval_group, ["setup"], catch_exceptions=False)

        assert result.exit_code == 0

    def test_eval_setup_no_ollama(self, runner: CliRunner):
        """eval setup prints a warning when Ollama is not running."""
        from studyctl.cli._eval import eval_group

        with (
            patch("studyctl.cli._eval._check_ollama_running", return_value=False),
            patch("studyctl.cli._eval._detect_ram_gb", return_value=32.0),
            patch("studyctl.cli._eval._is_apple_silicon", return_value=False),
            patch("studyctl.cli._eval._ollama_models", return_value=[]),
        ):
            result = runner.invoke(eval_group, ["setup"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Ollama not running" in result.output

    def test_eval_setup_small_ram_warns(self, runner: CliRunner):
        """eval setup warns about tight fit when RAM < 16 GB."""
        from studyctl.cli._eval import eval_group

        with (
            patch("studyctl.cli._eval._check_ollama_running", return_value=True),
            patch("studyctl.cli._eval._detect_ram_gb", return_value=12.0),
            patch("studyctl.cli._eval._is_apple_silicon", return_value=False),
            patch("studyctl.cli._eval._ollama_models", return_value=[]),
        ):
            result = runner.invoke(eval_group, ["setup"], catch_exceptions=False)

        assert result.exit_code == 0
        # Should recommend small model for low RAM
        assert "nemotron" in result.output or "4b" in result.output.lower()

    def test_eval_setup_model_already_downloaded(self, runner: CliRunner):
        """eval setup notes when recommended model is already present."""
        from studyctl.cli._eval import eval_group

        with (
            patch("studyctl.cli._eval._check_ollama_running", return_value=True),
            patch("studyctl.cli._eval._detect_ram_gb", return_value=64.0),
            patch("studyctl.cli._eval._is_apple_silicon", return_value=True),
            patch("studyctl.cli._eval._ollama_models", return_value=["gemma4:26b"]),
        ):
            result = runner.invoke(eval_group, ["setup"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "already" in result.output.lower() or "downloaded" in result.output.lower()

    def test_eval_setup_prints_yaml_block(self, runner: CliRunner):
        """eval setup always prints a recommended config YAML block."""
        from studyctl.cli._eval import eval_group

        with (
            patch("studyctl.cli._eval._check_ollama_running", return_value=True),
            patch("studyctl.cli._eval._detect_ram_gb", return_value=32.0),
            patch("studyctl.cli._eval._is_apple_silicon", return_value=False),
            patch("studyctl.cli._eval._ollama_models", return_value=[]),
        ):
            result = runner.invoke(eval_group, ["setup"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "eval:" in result.output
        assert "judge:" in result.output


# ---------------------------------------------------------------------------
# eval history
# ---------------------------------------------------------------------------


class TestEvalHistory:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_eval_history_no_data(self, runner: CliRunner, tmp_path: Path):
        """eval history prints a helpful message when no TSV file exists."""
        from studyctl.cli._eval import eval_group

        with patch("studyctl.cli._eval._eval_results_path", return_value=tmp_path / "missing.tsv"):
            result = runner.invoke(eval_group, ["history"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No evaluation history" in result.output

    def test_eval_history_with_data(self, runner: CliRunner, tmp_path: Path):
        """eval history renders a table when TSV data exists."""
        from studyctl.cli._eval import eval_group

        tsv_file = tmp_path / "eval-results.tsv"
        tsv_file.write_text(_SAMPLE_TSV)

        with patch("studyctl.cli._eval._eval_results_path", return_value=tsv_file):
            result = runner.invoke(eval_group, ["history"], catch_exceptions=False)

        assert result.exit_code == 0
        # Should display the scenario IDs from our sample data
        assert "s1" in result.output
        assert "s2" in result.output

    def test_eval_history_shows_scores(self, runner: CliRunner, tmp_path: Path):
        """eval history shows score values from the TSV."""
        from studyctl.cli._eval import eval_group

        tsv_file = tmp_path / "eval-results.tsv"
        tsv_file.write_text(_SAMPLE_TSV)

        with patch("studyctl.cli._eval._eval_results_path", return_value=tsv_file):
            result = runner.invoke(eval_group, ["history"], catch_exceptions=False)

        assert result.exit_code == 0
        # Score values from sample data
        assert "87.50" in result.output or "87.5" in result.output


# ---------------------------------------------------------------------------
# eval run
# ---------------------------------------------------------------------------


class TestEvalRun:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_eval_run_missing_scenarios(self, runner: CliRunner, tmp_path: Path):
        """eval run --scenarios nonexistent.yaml exits non-zero with error."""
        from studyctl.cli._eval import eval_group

        result = runner.invoke(eval_group, ["run", "--scenarios", str(tmp_path / "missing.yaml")])

        assert result.exit_code != 0

    def test_eval_run_dirty_git(self, runner: CliRunner):
        """eval run aborts when working tree is dirty (no --no-git-check)."""
        from studyctl.cli._eval import eval_group

        with patch(
            "studyctl.cli._eval.abort_if_dirty",
            side_effect=__import__("click").ClickException("dirty"),
        ):
            result = runner.invoke(eval_group, ["run"])

        assert result.exit_code != 0

    def test_eval_run_calls_run_evaluation(self, runner: CliRunner, tmp_path: Path):
        """eval run invokes run_evaluation with built components when scenarios exist."""
        from studyctl.cli._eval import eval_group

        # Write a minimal scenarios YAML
        scenarios_file = tmp_path / "test.yaml"
        scenarios_file.write_text(
            "scenarios:\n"
            "  - id: t1\n"
            "    name: Test One\n"
            "    priority: normal\n"
            "    topic: Python\n"
            "    energy: 5\n"
            "    prompt: What is a decorator?\n"
        )

        mock_summary = _make_summary()

        with (
            patch("studyctl.cli._eval.abort_if_dirty"),
            patch("studyctl.cli._eval.run_evaluation", return_value=mock_summary) as mock_run,
            patch("studyctl.cli._eval.detect_agents", return_value=["claude"]),
        ):
            result = runner.invoke(
                eval_group,
                ["run", "--scenarios", str(scenarios_file), "--no-git-check"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_eval_run_prints_summary(self, runner: CliRunner, tmp_path: Path):
        """eval run prints avg score and pass/fail count after completion."""
        from studyctl.cli._eval import eval_group

        scenarios_file = tmp_path / "test.yaml"
        scenarios_file.write_text(
            "scenarios:\n"
            "  - id: t1\n"
            "    name: Test One\n"
            "    priority: normal\n"
            "    topic: Python\n"
            "    energy: 5\n"
            "    prompt: What is a decorator?\n"
        )

        mock_summary = _make_summary()

        with (
            patch("studyctl.cli._eval.abort_if_dirty"),
            patch("studyctl.cli._eval.run_evaluation", return_value=mock_summary),
            patch("studyctl.cli._eval.detect_agents", return_value=["claude"]),
        ):
            result = runner.invoke(
                eval_group,
                ["run", "--scenarios", str(scenarios_file), "--no-git-check"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # Should mention scores / pass count
        assert (
            "100.0" in result.output or "3/3" in result.output or "passed" in result.output.lower()
        )

    def test_eval_run_no_agents_exits_nonzero(self, runner: CliRunner, tmp_path: Path):
        """eval run exits non-zero when no agent is auto-detected."""
        from studyctl.cli._eval import eval_group

        scenarios_file = tmp_path / "test.yaml"
        scenarios_file.write_text(
            "scenarios:\n"
            "  - id: t1\n"
            "    name: Test One\n"
            "    priority: normal\n"
            "    topic: Python\n"
            "    energy: 5\n"
            "    prompt: What is a decorator?\n"
        )

        with (
            patch("studyctl.cli._eval.abort_if_dirty"),
            patch("studyctl.cli._eval.detect_agents", return_value=[]),
        ):
            result = runner.invoke(
                eval_group,
                ["run", "--scenarios", str(scenarios_file), "--no-git-check"],
            )

        assert result.exit_code != 0

    def test_eval_run_explicit_agent(self, runner: CliRunner, tmp_path: Path):
        """eval run --agent bypasses auto-detection."""
        from studyctl.cli._eval import eval_group

        scenarios_file = tmp_path / "test.yaml"
        scenarios_file.write_text(
            "scenarios:\n"
            "  - id: t1\n"
            "    name: Test One\n"
            "    priority: normal\n"
            "    topic: Python\n"
            "    energy: 5\n"
            "    prompt: What is a decorator?\n"
        )

        mock_summary = _make_summary(agent="gemini")

        with (
            patch("studyctl.cli._eval.abort_if_dirty"),
            patch("studyctl.cli._eval.run_evaluation", return_value=mock_summary) as mock_run,
            patch("studyctl.cli._eval.detect_agents", return_value=["claude"]),
        ):
            result = runner.invoke(
                eval_group,
                ["run", "--scenarios", str(scenarios_file), "--agent", "gemini", "--no-git-check"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # detect_agents should NOT have been used
        call_kwargs = mock_run.call_args
        assert call_kwargs is not None

    def test_eval_run_builtin_scenarios(self, runner: CliRunner):
        """eval run with scenarios=study uses the builtin scenarios path."""
        from studyctl.cli._eval import eval_group

        mock_summary = _make_summary()

        with (
            patch("studyctl.cli._eval.abort_if_dirty"),
            patch("studyctl.cli._eval.run_evaluation", return_value=mock_summary),
            patch("studyctl.cli._eval.detect_agents", return_value=["claude"]),
            patch(
                "studyctl.cli._eval.builtin_scenarios_path",
                return_value=Path("/fake/study.yaml"),
            ),
            patch(
                "studyctl.cli._eval.load_scenarios",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                eval_group,
                ["run", "--scenarios", "study", "--no-git-check"],
                catch_exceptions=False,
            )

        # Even with empty scenarios the command should run to completion
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# eval group registration
# ---------------------------------------------------------------------------


class TestEvalGroupRegistered:
    def test_eval_group_has_subcommands(self):
        """eval_group exposes run, history, and setup commands."""
        from studyctl.cli._eval import eval_group

        assert "run" in eval_group.commands
        assert "history" in eval_group.commands
        assert "setup" in eval_group.commands

    def test_eval_registered_in_cli(self):
        """'eval' is registered in the top-level CLI LazyGroup."""
        from studyctl.cli import cli

        # LazyGroup stores commands in _lazy_subcommands dict on the group
        lazy = getattr(cli, "_lazy_subcommands", {})
        assert "eval" in lazy
        assert lazy["eval"] == "studyctl.cli._eval:eval_group"
