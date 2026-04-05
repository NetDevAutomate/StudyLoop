"""LLM-backed rubric judge combining heuristic pre-flight with LLM scoring."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from studyctl.eval.judge.heuristic import run_heuristics
from studyctl.eval.llm_client import LLMClient, LLMClientError
from studyctl.eval.models import JudgeResult, Scenario

logger = logging.getLogger(__name__)


class LLMJudge:
    """Judge that uses heuristic checks + LLM scoring."""

    DIMENSIONS: ClassVar[list[str]] = [
        "clarity",
        "socratic_quality",
        "emotional_safety",
        "energy_adaptation",
        "tool_usage",
        "topic_focus",
        "win_recognition",
    ]

    def __init__(self, llm_client: LLMClient) -> None:
        self.client = llm_client
        self._prompt_template = self._load_template()

    def _load_template(self) -> str:
        template_path = Path(__file__).parent.parent / "prompts" / "judge-rubric.md"
        return template_path.read_text()

    def score(self, scenario: Scenario, response: str) -> JudgeResult:
        """Score a single response: heuristic pre-flight then LLM rubric."""
        # 1. Run heuristic checks — fail fast if structural requirements unmet
        heuristic = run_heuristics(response, scenario)
        if not heuristic.passed:
            return JudgeResult(
                scenario_id=scenario.id,
                heuristic_pass=False,
                dimensions={},
                weights=scenario.rubric_weights,
            )

        # 2. Build prompt from template
        prompt = self._build_prompt(scenario, response)

        # 3. Call LLM
        try:
            raw = self.client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
            )
        except LLMClientError:
            logger.warning("LLM call failed for scenario %s", scenario.id)
            return JudgeResult(
                scenario_id=scenario.id,
                heuristic_pass=True,
                dimensions={},
                weights=scenario.rubric_weights,
                raw_response="LLM_ERROR",
            )

        # 4. Parse JSON scores, clamp to 1-4
        dimensions = self._parse_scores(raw)

        return JudgeResult(
            scenario_id=scenario.id,
            heuristic_pass=True,
            dimensions=dimensions,
            weights=scenario.rubric_weights,
            raw_response=raw,
        )

    def _build_prompt(self, scenario: Scenario, response: str) -> str:
        return (
            self._prompt_template.replace("{{scenario_name}}", scenario.name)
            .replace("{{energy}}", str(scenario.energy))
            .replace("{{elapsed_minutes}}", str(scenario.elapsed_minutes))
            .replace("{{topic}}", scenario.topic)
            .replace("{{prompt}}", scenario.prompt)
            .replace("{{response}}", response)
        )

    def _parse_scores(self, raw: str) -> dict[str, int]:
        """Extract and clamp dimension scores from LLM JSON response."""
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            data = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.warning("Could not parse LLM response as JSON: %r", raw[:200])
            return dict.fromkeys(self.DIMENSIONS, 1)

        result: dict[str, int] = {}
        for dim in self.DIMENSIONS:
            val = data.get(dim, 1)
            if isinstance(val, (int, float)):
                result[dim] = max(1, min(4, int(val)))
            else:
                result[dim] = 1
        return result
