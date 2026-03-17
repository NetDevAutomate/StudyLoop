"""Tests for doctor core checks."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path


class TestPythonVersionCheck:
    def test_python_312_passes(self):
        from studyctl.doctor.core import check_python_version

        with patch.object(sys, "version_info", (3, 12, 0, "final", 0)):
            results = check_python_version()
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_python_311_fails(self):
        from studyctl.doctor.core import check_python_version

        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            results = check_python_version()
        assert results[0].status == "fail"
        assert "3.12" in results[0].fix_hint


class TestStudyctlInstalledCheck:
    def test_studyctl_installed(self):
        from studyctl.doctor.core import check_studyctl_installed

        results = check_studyctl_installed()
        assert len(results) == 1
        assert results[0].status == "pass"


class TestAgentSessionToolsCheck:
    def test_installed(self):
        from studyctl.doctor.core import check_agent_session_tools

        with patch("importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = True
            with patch("studyctl.doctor.core._get_package_version", return_value="1.0.0"):
                results = check_agent_session_tools()
        assert results[0].status == "pass"

    def test_not_installed(self):
        from studyctl.doctor.core import check_agent_session_tools

        with patch("importlib.util.find_spec", return_value=None):
            results = check_agent_session_tools()
        assert results[0].status == "warn"
        assert "uv" in results[0].fix_hint


class TestConfigFileCheck:
    def test_config_exists_valid(self, tmp_path: Path):
        from studyctl.doctor.core import check_config_file

        config = tmp_path / "config.yaml"
        config.write_text("obsidian_base: ~/vault\n")
        with patch("studyctl.doctor.core._get_config_path", return_value=config):
            results = check_config_file()
        assert results[0].status == "pass"

    def test_config_missing(self, tmp_path: Path):
        from studyctl.doctor.core import check_config_file

        missing = tmp_path / "nope.yaml"
        with patch("studyctl.doctor.core._get_config_path", return_value=missing):
            results = check_config_file()
        assert results[0].status == "fail"
        assert "config init" in results[0].fix_hint

    def test_config_invalid_yaml(self, tmp_path: Path):
        from studyctl.doctor.core import check_config_file

        config = tmp_path / "config.yaml"
        config.write_text(": :\n  - [bad yaml\n")
        with patch("studyctl.doctor.core._get_config_path", return_value=config):
            results = check_config_file()
        assert results[0].status == "fail"
        assert "YAML" in results[0].message
