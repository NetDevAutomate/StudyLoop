"""Tests for doctor check result model and registry."""

from __future__ import annotations

import pytest


class TestCheckResult:
    def test_create_pass(self):
        from studyctl.doctor.models import CheckResult

        r = CheckResult(
            category="core",
            name="python_version",
            status="pass",
            message="Python 3.12.0",
            fix_hint="",
            fix_auto=False,
        )
        assert r.status == "pass"
        assert r.category == "core"

    def test_to_dict(self):
        from studyctl.doctor.models import CheckResult

        r = CheckResult(
            category="core",
            name="test",
            status="fail",
            message="broken",
            fix_hint="fix it",
            fix_auto=True,
        )
        d = r.to_dict()
        assert d["status"] == "fail"
        assert d["fix_auto"] is True
        assert set(d.keys()) == {"category", "name", "status", "message", "fix_hint", "fix_auto"}

    def test_invalid_status_raises(self):
        from studyctl.doctor.models import CheckResult

        with pytest.raises(ValueError, match="status"):
            CheckResult(
                category="core",
                name="test",
                status="invalid",
                message="bad",
                fix_hint="",
                fix_auto=False,
            )

    def test_invalid_category_raises(self):
        from studyctl.doctor.models import CheckResult

        with pytest.raises(ValueError, match="category"):
            CheckResult(
                category="bogus",
                name="test",
                status="pass",
                message="ok",
                fix_hint="",
                fix_auto=False,
            )


class TestCheckerRegistry:
    def test_register_and_run(self):
        from studyctl.doctor import CheckerRegistry
        from studyctl.doctor.models import CheckResult

        registry = CheckerRegistry()

        @registry.register("core")
        def check_dummy() -> list[CheckResult]:
            return [
                CheckResult(
                    category="core",
                    name="dummy",
                    status="pass",
                    message="ok",
                    fix_hint="",
                    fix_auto=False,
                )
            ]

        results = registry.run_all()
        assert len(results) == 1
        assert results[0].name == "dummy"

    def test_run_category_filter(self):
        from studyctl.doctor import CheckerRegistry
        from studyctl.doctor.models import CheckResult

        registry = CheckerRegistry()

        @registry.register("core")
        def check_core() -> list[CheckResult]:
            return [CheckResult("core", "c1", "pass", "ok", "", False)]

        @registry.register("config")
        def check_config() -> list[CheckResult]:
            return [CheckResult("config", "c2", "warn", "hmm", "", False)]

        results = registry.run_category("core")
        assert len(results) == 1
        assert results[0].category == "core"

    def test_checker_exception_returns_fail(self):
        from studyctl.doctor import CheckerRegistry

        registry = CheckerRegistry()

        @registry.register("core")
        def check_broken() -> list:
            raise RuntimeError("boom")

        results = registry.run_all()
        assert len(results) == 1
        assert results[0].status == "fail"
        assert "boom" in results[0].message
