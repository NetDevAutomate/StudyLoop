"""Protocol defining the interface for evaluation targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from studyctl.eval.models import Scenario


class EvalTarget(Protocol):
    name: str

    def setup(self, scenario: Scenario) -> None: ...

    def run(self, scenario: Scenario) -> str: ...

    def teardown(self) -> None: ...
