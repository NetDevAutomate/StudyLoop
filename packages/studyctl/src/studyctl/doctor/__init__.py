"""Doctor diagnostic engine — checker registry and runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from studyctl.doctor.models import CheckResult


class CheckerRegistry:
    """Registry of diagnostic checker functions, grouped by category."""

    def __init__(self) -> None:
        self._checkers: list[tuple[str, Callable[[], list[CheckResult]]]] = []

    def register(self, category: str) -> Callable:
        def decorator(fn: Callable[[], list[CheckResult]]) -> Callable:
            self._checkers.append((category, fn))
            return fn

        return decorator

    def run_all(self) -> list[CheckResult]:
        from studyctl.doctor.models import CheckResult

        results: list[CheckResult] = []
        for category, fn in self._checkers:
            try:
                results.extend(fn())
            except Exception as exc:
                results.append(
                    CheckResult(
                        category=category,
                        name=fn.__name__,
                        status="fail",
                        message=f"Checker crashed: {exc}",
                        fix_hint="Report this bug",
                        fix_auto=False,
                    )
                )
        return results

    def run_category(self, category: str) -> list[CheckResult]:
        from studyctl.doctor.models import CheckResult

        results: list[CheckResult] = []
        for cat, fn in self._checkers:
            if cat != category:
                continue
            try:
                results.extend(fn())
            except Exception as exc:
                results.append(
                    CheckResult(
                        category=cat,
                        name=fn.__name__,
                        status="fail",
                        message=f"Checker crashed: {exc}",
                        fix_hint="Report this bug",
                        fix_auto=False,
                    )
                )
        return results
