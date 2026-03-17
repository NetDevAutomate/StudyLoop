"""Tests for studyctl update and upgrade CLI commands."""

from __future__ import annotations

import os
import sqlite3
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from studyctl.doctor.models import CheckResult

if TYPE_CHECKING:
    from pathlib import Path


class TestUpdateCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_update_shows_versions(self, runner: CliRunner):
        from studyctl.cli._upgrade import update

        mock_results = [
            CheckResult(
                "updates", "update_studyctl", "warn", "2.0.0 -> 2.1.0", "studyctl upgrade", True
            ),
            CheckResult("core", "studyctl_installed", "pass", "studyctl 2.0.0", "", False),
        ]

        with patch("studyctl.cli._upgrade._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = mock_results
            result = runner.invoke(update)
        assert result.exit_code == 0
        assert "2.1.0" in result.output

    def test_update_json(self, runner: CliRunner):
        from studyctl.cli._upgrade import update

        mock_results = [
            CheckResult("updates", "update_studyctl", "pass", "studyctl 2.0.0 (latest)", "", False),
        ]

        with patch("studyctl.cli._upgrade._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = mock_results
            result = runner.invoke(update, ["--json"])
        import json

        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_update_always_exit_0(self, runner: CliRunner):
        from studyctl.cli._upgrade import update

        mock_results = [
            CheckResult(
                "updates", "update_studyctl", "warn", "update available", "studyctl upgrade", True
            ),
        ]

        with patch("studyctl.cli._upgrade._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = mock_results
            result = runner.invoke(update)
        assert result.exit_code == 0


class TestPackageManagerDetection:
    def test_detect_uv(self):
        from studyctl.cli._upgrade import _detect_package_manager

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="studyctl 2.0.0\n")
            result = _detect_package_manager()
        assert result == "uv"

    def test_detect_brew(self):
        from studyctl.cli._upgrade import _detect_package_manager

        def side_effect(cmd, **kw):
            if "uv" in cmd:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="studyctl\n")

        with patch("subprocess.run", side_effect=side_effect):
            result = _detect_package_manager()
        assert result == "brew"

    def test_fallback_pip(self):
        from studyctl.cli._upgrade import _detect_package_manager

        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            result = _detect_package_manager()
        assert result == "pip"


class TestDbBackup:
    def test_backup_created(self, tmp_path: Path):
        from studyctl.cli._upgrade import _backup_database

        db = tmp_path / "test.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        backup_dir = tmp_path / "backups"
        result = _backup_database(db, backup_dir)
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

    def test_backup_missing_db_returns_none(self, tmp_path: Path):
        from studyctl.cli._upgrade import _backup_database

        missing = tmp_path / "nope.db"
        backup_dir = tmp_path / "backups"
        result = _backup_database(missing, backup_dir)
        assert result is None

    def test_backup_pruning(self, tmp_path: Path):
        from studyctl.cli._upgrade import _prune_old_backups

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        for i in range(5):
            f = backup_dir / f"test.db.bak.2026010{i}"
            f.write_text("fake")
            if i < 3:
                old_time = time.time() - (31 * 86400)
                os.utime(f, (old_time, old_time))

        _prune_old_backups(backup_dir, max_age_days=30)
        remaining = list(backup_dir.iterdir())
        assert len(remaining) == 2


class TestUpgradeCommand:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run(self, runner: CliRunner):
        from studyctl.cli._upgrade import upgrade

        mock_results = [
            CheckResult(
                "updates", "update_studyctl", "warn", "2.0.0 -> 2.1.0", "studyctl upgrade", True
            ),
        ]

        with patch("studyctl.cli._upgrade._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = mock_results
            result = runner.invoke(upgrade, ["--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would" in result.output.lower()

    def test_nothing_to_upgrade(self, runner: CliRunner):
        from studyctl.cli._upgrade import upgrade

        mock_results = [
            CheckResult("core", "python_version", "pass", "Python 3.12", "", False),
        ]

        with patch("studyctl.cli._upgrade._get_registry") as mock_reg:
            mock_reg.return_value.run_all.return_value = mock_results
            result = runner.invoke(upgrade)
        assert result.exit_code == 0
        assert "up to date" in result.output.lower()
