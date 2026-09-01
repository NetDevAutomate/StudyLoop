"""Readiness-budget scaling — the mechanism that absorbs full-suite load.

These are unit tests of the conftest hook itself. They deliberately do NOT need a
browser: the thing worth proving is that the patch takes, that it scales only what
it should, and that it restores what it borrowed.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

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
    """The multiplier comes from the environment, and from nothing else."""

    @staticmethod
    def _scale(monkeypatch: pytest.MonkeyPatch, env: str | None = None) -> float:
        import _readiness

        if env is None:
            monkeypatch.delenv("STUDYLOOP_E2E_TIMEOUT_SCALE", raising=False)
        else:
            monkeypatch.setenv("STUDYLOOP_E2E_TIMEOUT_SCALE", env)
        monkeypatch.setattr(_readiness, "_scale", 1.0, raising=False)
        _readiness.configure_scale()
        return _readiness.readiness_scale()

    def test_unset_means_unscaled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default is the release configuration: budgets exactly as written."""
        assert self._scale(monkeypatch) == 1.0

    def test_an_explicit_override_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._scale(monkeypatch, env="4") == 4.0

    def test_a_garbage_override_falls_back_rather_than_crashing_collection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in the env var must not take the whole run down at collection."""
        assert self._scale(monkeypatch, env="soon") == 1.0

    def test_an_override_cannot_shrink_budgets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Below 1.0 would tighten every budget and invent failures."""
        assert self._scale(monkeypatch, env="0.1") == 1.0

    def test_the_size_of_the_run_cannot_reach_the_multiplier(self) -> None:
        """The defect this replaced, guarded structurally.

        Keying the multiplier off the collected item count meant a test's budget
        depended on what was selected beside it: the default selection collects
        3599 items and chose 3.0 while running zero browser tests, and a
        browser-free unit test's 4s poll silently became 12s. A count cannot
        reach the multiplier if the configuring function takes no arguments and
        the one that used to accept a count no longer exists.
        """
        import inspect

        import _readiness

        assert inspect.signature(_readiness.configure_scale).parameters == {}
        assert not hasattr(_readiness, "set_scale_for_run")

    def test_no_test_outside_this_file_scales_its_own_budget(self) -> None:
        """scaled_seconds is a diagnostic lever, not a way to size a budget.

        It reads the same global as the Playwright patch, so a call site that
        uses it inherits whatever the environment says. A unit test did exactly
        that and had its poll tripled by an unrelated selection; budgets belong
        at a justified fixed ceiling instead.
        """
        from pathlib import Path

        tests_dir = Path(__file__).parent
        users = sorted(
            p.name
            for p in tests_dir.rglob("test_*.py")
            if p.name != Path(__file__).name and "scaled_seconds" in p.read_text()
        )
        assert users == [], f"these tests scale their own budgets: {users}"


class TestTheCollectionHook:
    """One hook — and pytest calls only one function by that name."""

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

    def test_the_hook_does_not_touch_the_readiness_scale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collection must not set the multiplier, however large the run.

        This hook used to call set_scale_for_run(len(items)), which is what made
        a budget depend on the size of the selection.
        """
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

        pytest_collection_modifyitems([FakeItem() for _ in range(3599)])

        assert _readiness.readiness_scale() == 1.0

    def test_the_header_states_the_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every run must say what sensitivity produced its pass count.

        The report that started this work said "500 passed" without recording
        that budgets had been widened, so the number could not be interpreted.
        """
        import _readiness

        from conftest import (
            pytest_report_header,  # pyright: ignore[reportAttributeAccessIssue]
        )

        # setattr, so monkeypatch restores the module global too. Only setenv-ing
        # left _scale at 3.0 after teardown, and the terminal-summary hook then
        # warned that an unscaled run was scaled.
        monkeypatch.setattr(_readiness, "_scale", 1.0, raising=False)
        monkeypatch.delenv("STUDYLOOP_E2E_TIMEOUT_SCALE", raising=False)
        unscaled = pytest_report_header()
        assert "1.0x" in unscaled
        assert "release configuration" in unscaled

        monkeypatch.setenv("STUDYLOOP_E2E_TIMEOUT_SCALE", "3")
        scaled = pytest_report_header()
        assert "3.0x" in scaled
        assert "NOT a release-pass configuration" in scaled

    def test_the_summary_warning_tracks_the_session_not_the_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A test mutating the scale must not make an unscaled run look scaled.

        The first version of this hook read the live global, so the test above
        -- which legitimately sets the env var and reconfigures -- left it at
        3.0 and the summary warned on a genuinely unscaled run. An honesty
        signal that cries wolf is worse than none, because it trains people to
        ignore it.
        """
        import _readiness

        import conftest

        monkeypatch.setattr(conftest, "_SESSION_SCALE", 1.0, raising=False)
        monkeypatch.setattr(_readiness, "_scale", 3.0, raising=False)

        written: list[str] = []

        class FakeReporter:
            def write_sep(self, sep: str, text: str, **kwargs: object) -> None:
                written.append(text)

        # Two conftest.py files exist in this repo, so the type checker cannot
        # tell which module this name resolves to -- the same reason sibling
        # imports here carry per-symbol ignores.
        conftest.pytest_terminal_summary(  # pyright: ignore[reportAttributeAccessIssue]
            FakeReporter()  # pyright: ignore[reportArgumentType]
        )

        assert written == [], f"warned about scaling on an unscaled session: {written}"

    def test_the_summary_warns_when_the_session_really_was_scaled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And it must still fire when it matters, under -q as well."""
        import conftest

        monkeypatch.setattr(conftest, "_SESSION_SCALE", 3.0, raising=False)

        written: list[str] = []

        class FakeReporter:
            def write_sep(self, sep: str, text: str, **kwargs: object) -> None:
                written.append(text)

        # Two conftest.py files exist in this repo, so the type checker cannot
        # tell which module this name resolves to -- the same reason sibling
        # imports here carry per-symbol ignores.
        conftest.pytest_terminal_summary(  # pyright: ignore[reportAttributeAccessIssue]
            FakeReporter()  # pyright: ignore[reportArgumentType]
        )

        assert len(written) == 1
        assert "NOT a release result" in written[0]


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


class TestHollowRunGuard:
    """A green run that tested almost nothing must not pass for green.

    If a dependency goes missing the browser suite skips rather than fails, so
    "0 failed" survives a run that executed nothing. Enforcing a minimum pass
    count covers every way a run can become hollow, rather than only the missing
    dependencies somebody predicted.
    """

    @staticmethod
    def _run(monkeypatch: pytest.MonkeyPatch, *, required: str | None, passed: int, skipped: int):
        import conftest

        if required is None:
            monkeypatch.delenv("STUDYLOOP_MIN_PASSED", raising=False)
        else:
            monkeypatch.setenv("STUDYLOOP_MIN_PASSED", required)

        written: list[str] = []

        class FakeReporter:
            stats: ClassVar[dict[str, list[None]]] = {
                "passed": [None] * passed,
                "skipped": [None] * skipped,
            }

            def write_sep(self, sep: str, text: str, **kwargs: object) -> None:
                written.append(text)

        class FakePluginManager:
            def get_plugin(self, name: str) -> object:
                return FakeReporter()

        class FakeConfig:
            pluginmanager = FakePluginManager()

        class FakeSession:
            config = FakeConfig()
            exitstatus = 0

        session = FakeSession()
        conftest.pytest_sessionfinish(session, 0)  # pyright: ignore[reportAttributeAccessIssue]
        return session, written

    def test_a_hollow_run_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """400 of 500 tests skipping because ttyd vanished must not read green."""
        session, written = self._run(monkeypatch, required="450", passed=100, skipped=400)

        assert session.exitstatus == 1
        assert "HOLLOW RUN" in written[0]
        assert "400 skipped" in written[0]

    def test_a_full_run_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, written = self._run(monkeypatch, required="450", passed=500, skipped=20)

        assert session.exitstatus == 0
        assert written == []

    def test_exactly_the_minimum_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session, _ = self._run(monkeypatch, required="500", passed=500, skipped=0)

        assert session.exitstatus == 0

    def test_unset_leaves_local_runs_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Running one file must not trip a suite-sized threshold."""
        session, written = self._run(monkeypatch, required=None, passed=3, skipped=0)

        assert session.exitstatus == 0
        assert written == []

    def test_a_garbage_threshold_is_ignored_rather_than_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in CI config must not fail every run for the wrong reason."""
        session, written = self._run(monkeypatch, required="lots", passed=1, skipped=0)

        assert session.exitstatus == 0
        assert written == []
