"""Tests for studyloop doctor CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from studyloop.doctor.models import CheckResult

HEALTHY_RESULTS = [
    CheckResult("core", "python_version", "pass", "Python 3.12.0", "", False),
    CheckResult("core", "config_file", "pass", "Config valid", "", False),
]
WARN_AUTO_RESULTS = [
    CheckResult("core", "python_version", "pass", "Python 3.12.0", "", False),
    CheckResult("updates", "update_studyloop", "warn", "2.0.0 -> 2.1.0", "studyloop upgrade", True),
]
FAIL_RESULTS = [
    CheckResult("core", "config_file", "fail", "Config missing", "studyloop config init", True),
]
CORE_FAIL_RESULTS = [
    CheckResult("core", "studyloop_installed", "fail", "studyloop not found", "", False),
]


class TestDoctorCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_healthy_exit_0(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 0

    def test_warn_auto_exit_1(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = WARN_AUTO_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 1

    def test_fail_exit_1(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = FAIL_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 1

    def test_core_fail_exit_2(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = CORE_FAIL_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 2

    def test_json_output(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, ["--json"], catch_exceptions=False)
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["category"] == "core"

    def test_quiet_output(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, ["--quiet"], catch_exceptions=False)
        assert "passed" in result.output.lower()
        assert "python_version" not in result.output

    def test_category_filter(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with patch("studyloop.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_category.return_value = HEALTHY_RESULTS[:1]
            result = runner.invoke(doctor, ["--category", "core"], catch_exceptions=False)
        mock_reg.return_value.run_category.assert_called_once_with("core")
        assert result.exit_code == 0

    def test_category_updates_is_hidden_until_a_release_exists(self, runner: CliRunner):
        """R-38: `--category updates` was an advertised, `--help`-listed

        choice that always produced zero results (check_pypi_versions is
        deliberately unregistered -- nothing is published yet). A `--fix`
        branch for it was unreachable dead code. Rather than a real category
        silently doing nothing, it should not be offered as a choice at all
        until a release exists.
        """
        from studyloop.cli._doctor import doctor

        result = runner.invoke(doctor, ["--category", "updates"])
        assert result.exit_code != 0
        assert "not one of" in result.output.lower()

        category_param = next(p for p in doctor.params if p.name == "category")
        assert isinstance(category_param.type, click.Choice)
        assert "updates" not in category_param.type.choices

    def test_fix_applies_and_reruns(self, runner: CliRunner):
        from studyloop.cli._doctor import doctor

        with (
            patch("studyloop.cli._doctor._get_registry") as mock_reg,
            patch("studyloop.cli._doctor._apply_fixes", return_value=["created config"]),
        ):
            mock_reg.return_value.run_all.side_effect = [FAIL_RESULTS, HEALTHY_RESULTS]
            result = runner.invoke(doctor, ["--fix"], catch_exceptions=False)

        assert result.exit_code == 0
        assert mock_reg.return_value.run_all.call_count == 2
        assert "Applied fixes" in result.output


class TestUnknownConfigKeysCheck:
    """R-34: a retired or misspelled top-level config.yaml key is silently
    inert today. This check names it instead. Defined in cli/_doctor.py
    (not doctor/config.py, which is owned by a different remediation lane)."""

    def test_orphaned_ttyd_port_key_is_named_unknown(self, tmp_path, monkeypatch) -> None:
        """ttyd_port survives in a pre-retirement config.yaml as dead weight;
        doctor must name it as unknown/retired, not stay silent."""
        from studyloop.cli._doctor import check_unknown_config_keys

        config = tmp_path / "config.yaml"
        config.write_text("ttyd_port: 7681\nweb_port: 9000\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

        results = check_unknown_config_keys()

        assert len(results) == 1
        assert results[0].status == "warn"
        assert "ttyd_port" in results[0].message
        assert "ttyd_port" in results[0].fix_hint

    def test_no_warning_for_a_config_with_only_known_keys(self, tmp_path, monkeypatch) -> None:
        from studyloop.cli._doctor import check_unknown_config_keys

        config = tmp_path / "config.yaml"
        config.write_text("web_port: 9000\nbrowser: firefox\ntts:\n  backend: kokoro\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

        assert check_unknown_config_keys() == []

    def test_no_warning_when_config_file_absent(self, tmp_path, monkeypatch) -> None:
        from studyloop.cli._doctor import check_unknown_config_keys

        monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "does-not-exist.yaml"))

        assert check_unknown_config_keys() == []


# ---------------------------------------------------------------------------
# Item 3 (D-C, deviation 12 kept): husk discovery
# ---------------------------------------------------------------------------

_HUSK_BLOCKERS = (
    "Mission 'why' is empty — interview the learner first.",
    "No observable success criteria.",
)


def _write_husk(plans_dir, plan_id: str, title: str, *, created: str = "") -> None:
    """An *active* document with no mission — the shape the readiness gate
    refuses to write to. Only a hand edit or a pre-gate import produces one;
    the seam never will, which is exactly why the fixture is a raw file."""
    created_line = f"created: {created}\n" if created else ""
    (plans_dir / f"{plan_id}.md").write_text(
        f"---\nid: {plan_id}\ntitle: {title}\nstatus: active\ntopics: [sql]\n{created_line}---\n\n"
        f"# {title}\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )


class TestStudyPlansCheck:
    """D-C: a legacy active-but-unready document (a "husk") refuses every
    write until it is paused or repaired, and until now nothing told the
    learner it existed before they tripped over the refusal. ``doctor`` names
    each husk with its blockers, an honest provenance hint, and both ways out
    — one ``warn`` row per husk, ``fix_auto=False`` (the repair is a
    conversation, not a script). Lives in ``cli/_doctor.py`` beside
    ``check_unknown_config_keys`` and joins the same ``config`` category: the
    health spec enumerates categories verbatim and gains none here."""

    @pytest.fixture(autouse=True)
    def _isolated_plans(self, tmp_path, monkeypatch):
        from studyloop.planning import store

        monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
        monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
        self.plans_dir = store.plans_dir()

    def test_doctor_names_each_active_but_unready_plan_with_its_blockers(self) -> None:
        from studyloop.cli._doctor import check_study_plans
        from studyloop.planning import CreatePlan, PlanApplication

        app = PlanApplication()
        app.apply(
            CreatePlan(
                title="Ready Active",
                plan_id="ready-active",
                status="active",
                answers={
                    "why": "Own the nightly pipeline",
                    "success": ["Deploy unaided"],
                    "topics": ["data-engineering"],
                    "milestones": [{"title": "Job anatomy", "concepts": ["glue job"]}],
                },
            )
        )
        app.apply(CreatePlan(title="Vague Draft", plan_id="vague-draft"))  # unready, not active
        _write_husk(self.plans_dir, "old-husk", "Old Husk", created="2026-09-01T00:00:00+00:00")
        _write_husk(self.plans_dir, "new-husk", "New Husk")  # created now: after the gate

        results = check_study_plans()

        assert [r.status for r in results] == ["warn", "warn"], results
        assert all(r.category == "config" for r in results)
        assert all(r.name == "study_plans" for r in results)
        assert all(r.fix_auto is False for r in results)
        by_id = {("old-husk" if "old-husk" in r.message else "new-husk"): r for r in results}
        assert set(by_id) == {"old-husk", "new-husk"}

        old = by_id["old-husk"]
        assert "Old Husk" in old.message
        for blocker in _HUSK_BLOCKERS:
            assert blocker in old.message
        assert "predates the readiness gate" in old.message
        assert "studyloop plan repair old-husk" in old.fix_hint
        assert "studyloop plan status old-husk paused" in old.fix_hint

        new = by_id["new-husk"]
        assert "cannot tell how it got that way" in new.message
        assert "hand edit" not in new.message  # never claimed: an import looks the same
        assert "studyloop plan repair new-husk" in new.fix_hint

        joined = " ".join(r.message for r in results)
        assert "ready-active" not in joined
        assert "vague-draft" not in joined  # a draft is unready by nature, not a husk

    def test_all_active_plans_ready_is_one_pass_row(self) -> None:
        from studyloop.cli._doctor import check_study_plans
        from studyloop.planning import CreatePlan, PlanApplication

        PlanApplication().apply(
            CreatePlan(
                title="Ready Active",
                status="active",
                answers={
                    "why": "Own the nightly pipeline",
                    "success": ["Deploy unaided"],
                    "topics": ["data-engineering"],
                    "milestones": [{"title": "Job anatomy", "concepts": ["glue job"]}],
                },
            )
        )

        results = check_study_plans()

        assert len(results) == 1
        assert results[0].status == "pass"
        assert results[0].category == "config"
        assert "1 active plan" in results[0].message
        assert "ready" in results[0].message

    def test_no_plans_at_all_is_info_not_a_warning(self) -> None:
        from studyloop.cli._doctor import check_study_plans

        results = check_study_plans()

        assert len(results) == 1
        assert results[0].status == "info"
        assert results[0].category == "config"

    def test_study_plans_check_is_registered_under_config(self) -> None:
        """The registry is what ``studyloop doctor`` runs; a checker that is
        defined but never registered is a test that passes and a doctor that
        stays silent."""
        from studyloop.cli._doctor import _get_registry

        registered = {(category, fn.__name__) for category, fn in _get_registry()._checkers}

        assert ("config", "check_study_plans") in registered
