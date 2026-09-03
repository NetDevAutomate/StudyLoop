"""Tests for studyloop doctor CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

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
