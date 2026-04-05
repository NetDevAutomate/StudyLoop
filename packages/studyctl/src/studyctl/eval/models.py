"""Data models for the persona evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field

PASS_THRESHOLD = 70.0


@dataclass
class Scenario:
    """A single evaluation scenario loaded from YAML."""

    id: str
    name: str
    priority: str  # critical, high, normal
    topic: str
    energy: int
    prompt: str
    elapsed_minutes: int = 10
    setup_prompts: list[str] = field(default_factory=list)
    heuristic_checks: list[str] = field(default_factory=list)
    rubric_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class HeuristicResult:
    """Result of running fast pre-flight checks on an agent response."""

    passed: bool
    checks: dict[str, bool]
    messages: list[str] = field(default_factory=list)


@dataclass
class JudgeResult:
    """LLM judge evaluation result for a single scenario."""

    scenario_id: str
    heuristic_pass: bool
    dimensions: dict[str, int]  # dimension → score 1-4
    weights: dict[str, float]
    raw_response: str = ""

    @property
    def weighted_score(self) -> float:
        """Percentage score 0-100, or 0.0 if heuristic failed or no dimensions."""
        if not self.heuristic_pass or not self.dimensions:
            return 0.0
        weighted_sum = sum(self.dimensions[d] * self.weights.get(d, 1.0) for d in self.dimensions)
        max_sum = sum(4.0 * self.weights.get(d, 1.0) for d in self.dimensions)
        return (weighted_sum / max_sum) * 100 if max_sum > 0 else 0.0

    @property
    def passed(self) -> bool:
        """True iff heuristic passed and weighted score >= PASS_THRESHOLD."""
        return self.heuristic_pass and self.weighted_score >= PASS_THRESHOLD

    @staticmethod
    def timeout(scenario_id: str) -> JudgeResult:
        """Factory for a timed-out evaluation result."""
        return JudgeResult(
            scenario_id=scenario_id,
            heuristic_pass=False,
            dimensions={},
            weights={},
            raw_response="TIMEOUT",
        )


@dataclass
class EvalSummary:
    """Aggregate results for one full persona evaluation run."""

    agent: str
    persona_hash: str
    commit: str
    results: list[JudgeResult]
    timestamp: str = ""

    @property
    def avg_score(self) -> float:
        """Mean weighted score across all results, 0.0 if empty."""
        scores = [r.weighted_score for r in self.results]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def all_passed(self) -> bool:
        """True iff every result passed."""
        return all(r.passed for r in self.results)
