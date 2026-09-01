"""Readiness-budget scaling — the mechanism that absorbs full-suite load.

These are unit tests of the conftest hook itself. They deliberately do NOT need a
browser: the thing worth proving is that the patch takes, that it scales only what
it should, and that it restores what it borrowed.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest


class TestScalingContract:
    """The Playwright surface the hook depends on must stay as assumed."""

    def test_patched_methods_exist_and_are_settable(self) -> None:
        """The hook patches class attributes; assert they are plain functions.

        Playwright's sync API is generated code. If a future version turned these
        into slots, properties or C-level descriptors, setattr would fail or
        silently not take, and every scaled budget would quietly revert to its
        unscaled value -- the flakes would come back looking like a new problem.
        """
        pw = pytest.importorskip("playwright.sync_api")
        from _readiness import SCALED_CALLS

        for class_name, method_name in SCALED_CALLS:
            cls = getattr(pw, class_name, None)
            assert cls is not None, f"playwright.sync_api has no {class_name}"
            method = getattr(cls, method_name, None)
            assert method is not None, f"{class_name} has no {method_name}"
            assert inspect.isfunction(method), (
                f"{class_name}.{method_name} is {type(method).__name__}, not a plain "
                "function -- the conftest patch may not take"
            )

    def test_timeout_is_keyword_only_on_every_patched_call(self) -> None:
        """The wrapper scales ``kwargs['timeout']``, so positional would slip past.

        Keyword-only is what makes the wrapper complete rather than best-effort.
        """
        pw = pytest.importorskip("playwright.sync_api")
        from _readiness import SCALED_CALLS

        for class_name, method_name in SCALED_CALLS:
            method = getattr(getattr(pw, class_name), method_name)
            param = inspect.signature(method).parameters.get("timeout")
            assert param is not None, f"{class_name}.{method_name} lost its timeout"
            assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
                f"{class_name}.{method_name} timeout is {param.kind.name}; the "
                "conftest wrapper only scales keyword arguments"
            )


class TestScaleSelection:
    """The multiplier is derived from the size of the run."""

    @staticmethod
    def _scale_for(count: int, monkeypatch: pytest.MonkeyPatch, env: str | None = None) -> float:
        import _readiness

        if env is None:
            monkeypatch.delenv("STUDYLOOP_E2E_TIMEOUT_SCALE", raising=False)
        else:
            monkeypatch.setenv("STUDYLOOP_E2E_TIMEOUT_SCALE", env)
        monkeypatch.setattr(_readiness, "_scale", 1.0, raising=False)
        _readiness.set_scale_for_run(count)
        return _readiness.readiness_scale()

    def test_single_file_run_is_left_exactly_as_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One file on an idle machine gets no allowance, so a hang fails fast."""
        assert self._scale_for(7, monkeypatch) == 1.0

    def test_a_large_run_gets_headroom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """~500 browser tests contending for CPU, disk and ports."""
        assert self._scale_for(500, monkeypatch) == 3.0

    def test_a_mid_sized_run_gets_some(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._scale_for(120, monkeypatch) == 2.0

    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._scale_for(7, monkeypatch, env="4") == 4.0

    def test_a_garbage_override_falls_back_rather_than_crashing_collection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in the env var must not take the whole run down at collection."""
        assert self._scale_for(500, monkeypatch, env="soon") == 1.0

    def test_an_override_cannot_shrink_budgets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Below 1.0 would tighten every budget and invent failures."""
        assert self._scale_for(500, monkeypatch, env="0.1") == 1.0


class TestTheHookDoesBothJobs:
    """One hook, two responsibilities — and pytest only calls one by that name."""

    def test_e2e_items_still_get_their_per_test_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The readiness scale must not have displaced the e2e timeout marker.

        pytest resolves ``pytest_collection_modifyitems`` by NAME, so a second
        definition in the same conftest replaces the first rather than running
        beside it. Adding the readiness scale as its own hook silently dropped this
        marker, which would have turned a hanging e2e test from a 300s failure into
        a run that never ends. Nothing covered it, so nothing failed.
        """

        # from-import so the one suppression covers it; `conftest.X` would need
        # one at every use site.
        from conftest import (
            E2E_TIMEOUT_SECONDS,  # pyright: ignore[reportAttributeAccessIssue]
            pytest_collection_modifyitems,  # pyright: ignore[reportAttributeAccessIssue]
        )

        applied: list[Any] = []

        class FakeItem:
            def __init__(self, markers: set[str]) -> None:
                self._markers = markers

            def get_closest_marker(self, name: str):
                return object() if name in self._markers else None

            def add_marker(self, marker) -> None:
                applied.append(marker)

        e2e_item = FakeItem({"e2e"})
        plain_item = FakeItem(set())
        already_timed = FakeItem({"e2e", "timeout"})

        monkeypatch.delenv("STUDYLOOP_E2E_TIMEOUT_SCALE", raising=False)
        pytest_collection_modifyitems([e2e_item, plain_item, already_timed])

        assert len(applied) == 1, (
            f"expected exactly one timeout marker (the bare e2e item), got {len(applied)}"
        )
        assert applied[0].args == (E2E_TIMEOUT_SECONDS,), (
            f"expected a {E2E_TIMEOUT_SECONDS}s budget, got {applied[0].args}"
        )

    def test_the_same_call_also_sets_the_readiness_scale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both jobs happen in one pass, so neither can be lost again."""
        import _readiness

        from conftest import (
            pytest_collection_modifyitems,  # pyright: ignore[reportAttributeAccessIssue]
        )

        monkeypatch.delenv("STUDYLOOP_E2E_TIMEOUT_SCALE", raising=False)
        monkeypatch.setattr(_readiness, "_scale", 1.0, raising=False)

        class FakeItem:
            def get_closest_marker(self, name: str) -> None:
                return None

            def add_marker(self, marker) -> None:  # pragma: no cover
                raise AssertionError("a non-e2e item should not be marked")

        pytest_collection_modifyitems([FakeItem() for _ in range(500)])
        assert _readiness.readiness_scale() == 3.0


class TestScalingApplies:
    """The wrapper must actually multiply, and must put things back."""

    def test_it_scales_a_timeout_and_restores_the_original(self) -> None:
        """Exercised against a stand-in with the same keyword-only shape.

        Using a stand-in rather than the real Page keeps this a unit test of the
        arithmetic and the restore, with no browser and no event loop.
        """
        import functools

        scale = 3.0
        seen: dict[str, object] = {}

        class FakePage:
            def wait_for_function(self, expression: str, *, timeout: float | None = None) -> str:
                seen["timeout"] = timeout
                return "called"

        original = FakePage.wait_for_function

        def scaled(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                given = kwargs.get("timeout")
                if given:
                    kwargs["timeout"] = given * scale
                return fn(*args, **kwargs)

            return wrapper

        FakePage.wait_for_function = scaled(original)  # type: ignore[method-assign]
        try:
            page = FakePage()
            page.wait_for_function("() => true", timeout=5000)
            assert seen["timeout"] == 15000, "an explicit budget should be multiplied"

            seen.clear()
            page.wait_for_function("() => true")
            assert seen["timeout"] is None, (
                "a call with no timeout must stay untouched -- it already inherits "
                "Playwright's 30s default"
            )
        finally:
            FakePage.wait_for_function = original  # type: ignore[method-assign]

        assert FakePage.wait_for_function is original, "the patch must be reverted"
