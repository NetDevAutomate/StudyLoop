"""TSV reporter and markdown report generator for the evaluation harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from studyctl.eval.models import EvalSummary, JudgeResult

# Ordered dimension columns — zero-filled when absent from a JudgeResult.
DIMENSION_COLUMNS = [
    "clarity",
    "socratic_quality",
    "emotional_safety",
    "energy_adaptation",
    "tool_usage",
    "topic_focus",
    "win_recognition",
]

TSV_HEADER = (
    "timestamp\tagent\tpersona_hash\tscenario_id\t"
    "heuristic_pass\tweighted_score\t" + "\t".join(DIMENSION_COLUMNS) + "\tcommit\n"
)


class TSVReporter:
    """Append-only TSV recorder plus markdown report generator."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, summary: EvalSummary) -> None:
        """Append one TSV row per JudgeResult in *summary*.

        Writes the header if the file does not yet exist.
        """
        if not self.path.exists():
            self.path.write_text(TSV_HEADER)

        with self.path.open("a") as fh:
            for result in summary.results:
                fh.write(self._row(summary, result))

    def generate_markdown(self, summary: EvalSummary) -> str:
        """Return a markdown report string for *summary*."""
        lines: list[str] = [
            f"# Eval Report — {summary.timestamp}",
            "",
            f"**Agent:** {summary.agent} | "
            f"**Persona:** {summary.persona_hash} | "
            f"**Commit:** {summary.commit}",
            "",
            "## Results",
            "",
            "| Scenario | Pass | Score | Best | Worst |",
            "|----------|------|-------|------|-------|",
        ]

        for r in summary.results:
            pass_icon = "✓" if r.passed else "✗"
            score_pct = f"{r.weighted_score:.1f}%"

            if r.dimensions:
                best_dim = max(r.dimensions, key=lambda d: r.dimensions[d])
                worst_dim = min(r.dimensions, key=lambda d: r.dimensions[d])
                best_str = f"{best_dim} ({r.dimensions[best_dim]})"
                worst_str = f"{worst_dim} ({r.dimensions[worst_dim]})"
            else:
                best_str = "—"
                worst_str = "—"

            lines.append(
                f"| {r.scenario_id} | {pass_icon} | {score_pct} | {best_str} | {worst_str} |"
            )

        passed_count = sum(1 for r in summary.results if r.passed)
        total_count = len(summary.results)
        all_passed_str = "Yes" if summary.all_passed else "No"

        lines += [
            "",
            "## Summary",
            f"- **Average score:** {summary.avg_score:.1f}%",
            f"- **Passed:** {passed_count}/{total_count}",
            f"- **All passed:** {all_passed_str}",
        ]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _row(self, summary: EvalSummary, result: JudgeResult) -> str:
        dim_values = "\t".join(str(result.dimensions.get(d, 0)) for d in DIMENSION_COLUMNS)
        return (
            f"{summary.timestamp}\t"
            f"{summary.agent}\t"
            f"{summary.persona_hash}\t"
            f"{result.scenario_id}\t"
            f"{result.heuristic_pass}\t"
            f"{result.weighted_score:.2f}\t"
            f"{dim_values}\t"
            f"{summary.commit}\n"
        )
