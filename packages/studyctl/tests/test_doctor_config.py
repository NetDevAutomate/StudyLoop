"""Tests for doctor config checks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path


def _make_settings(**overrides):
    """Create a minimal mock Settings object."""
    from types import SimpleNamespace

    defaults = {
        "obsidian_base": "",
        "topics": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestObsidianVaultCheck:
    def test_valid_vault(self, tmp_path: Path):
        from studyctl.doctor.config import check_obsidian_vault

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        with patch(
            "studyctl.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(vault)),
        ):
            results = check_obsidian_vault()
        assert results[0].status == "pass"

    def test_not_configured(self):
        from studyctl.doctor.config import check_obsidian_vault

        with patch(
            "studyctl.doctor.config._load_settings", return_value=_make_settings(obsidian_base="")
        ):
            results = check_obsidian_vault()
        assert results[0].status == "info"

    def test_path_missing(self, tmp_path: Path):
        from studyctl.doctor.config import check_obsidian_vault

        with patch(
            "studyctl.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(tmp_path / "gone")),
        ):
            results = check_obsidian_vault()
        assert results[0].status == "warn"


class TestReviewDirectoriesCheck:
    def test_all_dirs_exist(self, tmp_path: Path):
        from studyctl.doctor.config import check_review_directories

        d1 = tmp_path / "cards"
        d1.mkdir()
        topics = [type("T", (), {"name": "test", "directory": str(d1)})()]
        with patch(
            "studyctl.doctor.config._load_settings", return_value=_make_settings(topics=topics)
        ):
            results = check_review_directories()
        assert all(r.status == "pass" for r in results)

    def test_missing_dir(self, tmp_path: Path):
        from studyctl.doctor.config import check_review_directories

        topics = [type("T", (), {"name": "test", "directory": str(tmp_path / "gone")})()]
        with patch(
            "studyctl.doctor.config._load_settings", return_value=_make_settings(topics=topics)
        ):
            results = check_review_directories()
        assert results[0].status == "warn"

    def test_no_topics_configured(self):
        from studyctl.doctor.config import check_review_directories

        with patch("studyctl.doctor.config._load_settings", return_value=_make_settings(topics=[])):
            results = check_review_directories()
        assert results[0].status == "info"


class TestPandocCheck:
    def test_pandoc_available(self):
        from studyctl.doctor.config import check_pandoc

        with patch("shutil.which", return_value="/usr/local/bin/pandoc"):
            results = check_pandoc()
        assert results[0].status == "pass"

    def test_pandoc_missing(self):
        from studyctl.doctor.config import check_pandoc

        with patch("shutil.which", return_value=None):
            results = check_pandoc()
        assert results[0].status == "info"
        assert "pandoc" in results[0].fix_hint.lower()
