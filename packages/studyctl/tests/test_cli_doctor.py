"""Tests for studyctl doctor CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from studyctl.doctor.models import CheckResult

HEALTHY_RESULTS = [
    CheckResult("core", "python_version", "pass", "Python 3.12.0", "", False),
    CheckResult("core", "config_file", "pass", "Config valid", "", False),
]
WARN_AUTO_RESULTS = [
    CheckResult("core", "python_version", "pass", "Python 3.12.0", "", False),
    CheckResult("updates", "update_studyctl", "warn", "2.0.0 -> 2.1.0", "studyctl upgrade", True),
]
FAIL_RESULTS = [
    CheckResult("core", "config_file", "fail", "Config missing", "studyctl config init", True),
]
CORE_FAIL_RESULTS = [
    CheckResult("core", "studyctl_installed", "fail", "studyctl not found", "", False),
]


class TestDoctorCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_healthy_exit_0(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 0

    def test_warn_auto_exit_1(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = WARN_AUTO_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 1

    def test_fail_exit_1(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = FAIL_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 1

    def test_core_fail_exit_2(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = CORE_FAIL_RESULTS
            result = runner.invoke(doctor, catch_exceptions=False)
        assert result.exit_code == 2

    def test_json_output(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, ["--json"], catch_exceptions=False)
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["category"] == "core"

    def test_quiet_output(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = HEALTHY_RESULTS
            result = runner.invoke(doctor, ["--quiet"], catch_exceptions=False)
        assert "passed" in result.output.lower()
        assert "python_version" not in result.output

    def test_category_filter(self, runner: CliRunner):
        from studyctl.cli._doctor import doctor

        with patch("studyctl.cli._doctor._get_registry") as mock_reg:
            mock_reg.return_value.run_category.return_value = HEALTHY_RESULTS[:1]
            result = runner.invoke(doctor, ["--category", "core"], catch_exceptions=False)
        mock_reg.return_value.run_category.assert_called_once_with("core")
        assert result.exit_code == 0
