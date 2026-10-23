"""Tests for doctor check result model and registry."""

from __future__ import annotations

import pytest


class TestCheckResult:
    def test_create_pass(self):
        from studyloop.doctor.models import CheckResult

        r = CheckResult(
            category="core",
            name="python_version",
            status="pass",
            message="Python 3.12.0",
        )
        assert r.status == "pass"
        assert r.category == "core"
        assert r.fix_command is None and r.fix_note is None and r.fix_auto is False

    def test_to_dict(self):
        from studyloop.doctor.models import CheckResult

        r = CheckResult(
            category="core",
            name="test",
            status="fail",
            message="broken",
            fix_command="studyloop doctor --fix",
            fix_note="fix it",
            fix_auto=True,
        )
        d = r.to_dict()
        assert d["status"] == "fail"
        assert d["fix_auto"] is True
        assert d["fix_command"] == "studyloop doctor --fix"
        assert d["fix_note"] == "fix it"
        assert d["fix_hint"] == "studyloop doctor --fix  (fix it)"
        assert set(d.keys()) == {
            "category",
            "name",
            "status",
            "message",
            "fix_command",
            "fix_note",
            "fix_hint",
            "fix_auto",
        }

    def test_invalid_status_raises(self):
        from studyloop.doctor.models import CheckResult

        with pytest.raises(ValueError, match="status"):
            CheckResult(category="core", name="test", status="invalid", message="bad")

    def test_invalid_category_raises(self):
        from studyloop.doctor.models import CheckResult

        with pytest.raises(ValueError, match="category"):
            CheckResult(category="bogus", name="test", status="pass", message="ok")


class TestFixHintIsDerived:
    """``fix_hint`` mixed a command with prose, so nothing could run it (review 5, larger #4b).

    ``fix_command`` is the exact copy-pasteable command and ``fix_note`` the prose;
    ``fix_hint`` is kept as a read-only property for the readers that predate the
    split (``studyloop upgrade``'s table, ``--json`` consumers, the older tests).
    """

    def test_a_command_with_a_note_splits_into_the_two_fields(self):
        from studyloop.doctor.models import CheckResult

        r = CheckResult(
            "agents",
            "claude_definition",
            "warn",
            "installed definition predates the fix",
            fix_command="studyloop install agents --tool claude",
            fix_note="your copy predates the fix",
        )

        assert r.fix_command == "studyloop install agents --tool claude"
        assert r.fix_note == "your copy predates the fix"
        assert r.fix_hint == "studyloop install agents --tool claude  (your copy predates the fix)"

    def test_a_command_alone_is_the_whole_hint(self):
        from studyloop.doctor.models import CheckResult

        r = CheckResult("core", "x", "warn", "m", fix_command="studyloop install tools")
        assert r.fix_hint == "studyloop install tools"

    def test_a_note_alone_is_the_whole_hint(self):
        from studyloop.doctor.models import CheckResult

        r = CheckResult("core", "x", "info", "m", fix_note="Report this bug")
        assert r.fix_hint == "Report this bug"

    def test_no_fix_is_an_empty_hint(self):
        from studyloop.doctor.models import CheckResult

        assert CheckResult("core", "x", "pass", "m").fix_hint == ""

    def test_the_hint_cannot_be_passed_to_the_constructor(self):
        """The legacy field is gone from the constructor, so a stale producer fails loudly."""
        from studyloop.doctor.models import CheckResult

        with pytest.raises(TypeError):
            CheckResult("core", "x", "pass", "m", fix_hint="x")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            CheckResult("core", "x", "pass", "m", "", False)  # type: ignore[misc]

    def test_a_blank_command_or_note_is_normalised_to_none(self):
        """``""`` and ``None`` mean the same thing: nothing to show."""
        from studyloop.doctor.models import CheckResult

        r = CheckResult("core", "x", "pass", "m", fix_command="", fix_note="")
        assert r.fix_command is None and r.fix_note is None
        assert r.to_dict()["fix_command"] is None

    def test_split_fix_hint_is_the_inverse_of_the_property(self):
        """For hints produced outside doctor/ (agent-session-tools' ``install_hint()``)."""
        from studyloop.doctor.models import CheckResult, split_fix_hint

        cases = {
            "studyloop install agents --tool claude  (your copy predates the fix)": (
                "studyloop install agents --tool claude",
                "your copy predates the fix",
            ),
            "cd /x && uv sync --all-packages --extra semantic  (just sync-semantic; the venv)": (
                "cd /x && uv sync --all-packages --extra semantic",
                "just sync-semantic; the venv",
            ),
            "session-maint embed": ("session-maint embed", None),
            "Legacy rows stay for history; they are not searchable. Nothing to fix.": (
                None,
                "Legacy rows stay for history; they are not searchable. Nothing to fix.",
            ),
            "": (None, None),
        }
        for hint, expected in cases.items():
            command, note = split_fix_hint(hint)
            assert (command, note) == expected, hint
            r = CheckResult("core", "x", "warn", "m", fix_command=command, fix_note=note)
            assert r.fix_hint == hint, hint

    def test_split_fix_hint_treats_prose_as_a_note(self):
        from studyloop.doctor.models import split_fix_hint

        assert split_fix_hint("Report this bug") == (None, "Report this bug")
        assert split_fix_hint("studyloop doctor --fix") == ("studyloop doctor --fix", None)
        assert split_fix_hint("") == (None, None)


class TestCheckerRegistry:
    def test_register_and_run(self):
        from studyloop.doctor import CheckerRegistry
        from studyloop.doctor.models import CheckResult

        registry = CheckerRegistry()

        @registry.register("core")
        def check_dummy() -> list[CheckResult]:
            return [CheckResult(category="core", name="dummy", status="pass", message="ok")]

        results = registry.run_all()
        assert len(results) == 1
        assert results[0].name == "dummy"

    def test_run_category_filter(self):
        from studyloop.doctor import CheckerRegistry
        from studyloop.doctor.models import CheckResult

        registry = CheckerRegistry()

        @registry.register("core")
        def check_core() -> list[CheckResult]:
            return [CheckResult("core", "c1", "pass", "ok")]

        @registry.register("config")
        def check_config() -> list[CheckResult]:
            return [CheckResult("config", "c2", "warn", "hmm")]

        results = registry.run_category("core")
        assert len(results) == 1
        assert results[0].category == "core"

    def test_checker_exception_returns_fail(self):
        from studyloop.doctor import CheckerRegistry

        registry = CheckerRegistry()

        @registry.register("core")
        def check_broken() -> list:
            raise RuntimeError("boom")

        results = registry.run_all()
        assert len(results) == 1
        assert results[0].status == "fail"
        assert "boom" in results[0].message
