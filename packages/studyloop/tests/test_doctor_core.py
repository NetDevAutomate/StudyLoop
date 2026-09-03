"""Tests for doctor core checks."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path


class TestPythonVersionCheck:
    def test_python_312_passes(self):
        from studyloop.doctor.core import check_python_version

        with patch.object(sys, "version_info", (3, 12, 0, "final", 0)):
            results = check_python_version()
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_python_311_fails(self):
        from studyloop.doctor.core import check_python_version

        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            results = check_python_version()
        assert results[0].status == "fail"
        assert "3.12" in results[0].fix_hint


class TestStudyloopInstalledCheck:
    def test_studyloop_installed(self):
        from studyloop.doctor.core import check_studyloop_installed

        results = check_studyloop_installed()
        assert len(results) == 1
        assert results[0].status == "pass"


class TestAgentSessionToolsCheck:
    def test_installed(self):
        from studyloop.doctor.core import check_agent_session_tools

        with patch("importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = True
            with patch("studyloop.doctor.core._get_package_version", return_value="1.0.0"):
                results = check_agent_session_tools()
        assert results[0].status == "pass"

    def test_not_installed(self):
        from studyloop.doctor.core import check_agent_session_tools

        with patch("importlib.util.find_spec", return_value=None):
            results = check_agent_session_tools()
        assert results[0].status == "warn"
        assert "install tools" in results[0].fix_hint


class TestConfigFileCheck:
    def test_config_exists_valid(self, tmp_path: Path):
        from studyloop.doctor.core import check_config_file

        config = tmp_path / "config.yaml"
        config.write_text("obsidian_base: ~/vault\n")
        with patch("studyloop.doctor.core._get_config_path", return_value=config):
            results = check_config_file()
        assert results[0].status == "pass"

    def test_config_missing(self, tmp_path: Path):
        from studyloop.doctor.core import check_config_file

        missing = tmp_path / "nope.yaml"
        with patch("studyloop.doctor.core._get_config_path", return_value=missing):
            results = check_config_file()
        assert results[0].status == "warn"
        assert "doctor --fix" in results[0].fix_hint

    def test_config_invalid_yaml(self, tmp_path: Path):
        from studyloop.doctor.core import check_config_file

        config = tmp_path / "config.yaml"
        config.write_text(": :\n  - [bad yaml\n")
        with patch("studyloop.doctor.core._get_config_path", return_value=config):
            results = check_config_file()
        assert results[0].status == "fail"
        assert "YAML" in results[0].message


class TestTmuxCheck:
    """R-36: `studyloop study` (the primary, most-documented command)

    depends on tmux via multiplexer.py/tmux.py, but neither `doctor` nor
    `self-test` checked for it before -- a user without tmux got no
    diagnostic warning until they hit a raw failure on their first
    `studyloop study`. Reuses tmux.py's own is_tmux_available() rather than
    re-implementing version detection.
    """

    def test_tmux_available_passes(self):
        from studyloop.doctor.core import check_tmux_available

        with patch("studyloop.doctor.core.is_tmux_available", return_value=True):
            results = check_tmux_available()
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_tmux_missing_or_too_old_warns_with_an_install_hint(self):
        from studyloop.doctor.core import check_tmux_available

        with patch("studyloop.doctor.core.is_tmux_available", return_value=False):
            results = check_tmux_available()
        assert len(results) == 1
        assert results[0].status == "warn"
        assert "tmux" in results[0].fix_hint.lower()
