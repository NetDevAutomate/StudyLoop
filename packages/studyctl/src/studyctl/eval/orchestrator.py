"""Evaluation orchestrator — runs scenarios through target + judge pipeline."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from studyctl.eval.git_ops import short_hash
from studyctl.eval.models import EvalSummary, JudgeResult

if TYPE_CHECKING:
    from studyctl.eval.judge.base import Judge
    from studyctl.eval.models import Scenario
    from studyctl.eval.reporter import TSVReporter
    from studyctl.eval.targets.base import EvalTarget

logger = logging.getLogger(__name__)


class EvalTimeout(Exception):  # noqa: N818
    """Raised when a scenario times out."""


def run_evaluation(
    target: EvalTarget,
    judge: Judge,
    scenarios: list[Scenario],
    reporter: TSVReporter,
    agent: str,
    persona_hash: str = "",
) -> EvalSummary:
    """Run all scenarios through the target + judge pipeline.

    Each scenario gets its own setup/teardown cycle (session isolation).
    """
    results: list[JudgeResult] = []

    for scenario in scenarios:
        logger.info("Scenario: %s", scenario.name)
        score: JudgeResult
        try:
            target.setup(scenario)
            response = target.run(scenario)
            score = judge.score(scenario, response)
        except EvalTimeout:
            logger.warning("Scenario %s timed out", scenario.id)
            score = JudgeResult.timeout(scenario.id)
        except Exception:
            logger.exception("Scenario %s failed unexpectedly", scenario.id)
            score = JudgeResult.timeout(scenario.id)
        finally:
            try:
                target.teardown()
            except Exception:
                logger.exception("Teardown failed for %s", scenario.id)

        results.append(score)
        logger.info(
            "  %s: %.1f%% (%s)",
            scenario.id,
            score.weighted_score,
            "PASS" if score.passed else "FAIL",
        )

    summary = EvalSummary(
        agent=agent,
        persona_hash=persona_hash,
        commit=short_hash(),
        results=results,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
    )

    reporter.record(summary)
    return summary
