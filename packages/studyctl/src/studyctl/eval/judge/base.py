"""Judge protocol — any scorer must satisfy this interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from studyctl.eval.models import JudgeResult, Scenario


class Judge(Protocol):
    def score(self, scenario: Scenario, response: str) -> JudgeResult:
        """Score a single response against the scenario rubric."""
        ...
