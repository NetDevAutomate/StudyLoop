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


def _make_obsidian_config(**overrides):
    """Create a minimal ObsidianConfig-like namespace for doctor tests."""
    from types import SimpleNamespace

    defaults = {
        "export_enabled": False,
        "vault_path": "",
        "memory_dir": "AgentMemory",
        "moc_dir": "AgentMemory/MOC",
        "backlinks": True,
        "granularity": "both",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestObsidianVaultCheck:
    def test_valid_vault(self, tmp_path: Path):
        from studyloop.doctor.config import check_obsidian_vault

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(vault)),
        ):
            results = check_obsidian_vault()
        assert results[0].status == "pass"

    def test_not_configured(self):
        from studyloop.doctor.config import check_obsidian_vault

        with patch(
            "studyloop.doctor.config._load_settings", return_value=_make_settings(obsidian_base="")
        ):
            results = check_obsidian_vault()
        assert results[0].status == "info"

    def test_path_missing(self, tmp_path: Path):
        from studyloop.doctor.config import check_obsidian_vault

        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(tmp_path / "gone")),
        ):
            results = check_obsidian_vault()
        assert results[0].status == "warn"


class TestReviewDirectoriesCheck:
    def test_all_dirs_exist(self, tmp_path: Path):
        from studyloop.doctor.config import check_review_directories

        d1 = tmp_path / "cards"
        d1.mkdir()
        topics = [type("T", (), {"name": "test", "directory": str(d1)})()]
        with patch(
            "studyloop.doctor.config._load_settings", return_value=_make_settings(topics=topics)
        ):
            results = check_review_directories()
        assert all(r.status == "pass" for r in results)

    def test_missing_dir(self, tmp_path: Path):
        from studyloop.doctor.config import check_review_directories

        topics = [type("T", (), {"name": "test", "directory": str(tmp_path / "gone")})()]
        with patch(
            "studyloop.doctor.config._load_settings", return_value=_make_settings(topics=topics)
        ):
            results = check_review_directories()
        assert results[0].status == "warn"

    def test_no_topics_configured(self):
        from studyloop.doctor.config import check_review_directories

        with patch(
            "studyloop.doctor.config._load_settings", return_value=_make_settings(topics=[])
        ):
            results = check_review_directories()
        assert results[0].status == "info"


class TestPandocCheck:
    def test_pandoc_available(self):
        from studyloop.doctor.config import check_pandoc

        with patch("shutil.which", return_value="/usr/local/bin/pandoc"):
            results = check_pandoc()
        assert results[0].status == "pass"

    def test_pandoc_missing(self):
        from studyloop.doctor.config import check_pandoc

        with patch("shutil.which", return_value=None):
            results = check_pandoc()
        assert results[0].status == "info"
        assert "pandoc" in results[0].fix_hint.lower()


class TestTmuxResurrectCheck:
    def test_no_tmux_returns_empty(self):
        from studyloop.doctor.config import check_tmux_resurrect

        with patch("studyloop.doctor.config.shutil.which", return_value=None):
            results = check_tmux_resurrect()
        assert results == []

    def test_no_resurrect_returns_pass(self, tmp_path: Path):
        from unittest.mock import MagicMock

        from studyloop.doctor.config import check_tmux_resurrect

        with (
            patch("studyloop.doctor.config.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.doctor.config.Path.home", return_value=tmp_path),
            patch("studyloop.doctor.config.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            results = check_tmux_resurrect()

        assert len(results) == 1
        assert results[0].status == "pass"
        assert "not detected" in results[0].message

    def test_resurrect_without_hook_warns(self, tmp_path: Path):
        from studyloop.doctor.config import check_tmux_resurrect

        # Create resurrect plugin dir
        plugin_dir = tmp_path / ".tmux" / "plugins" / "tmux-resurrect"
        plugin_dir.mkdir(parents=True)
        # Create tmux.conf without hook
        tmux_conf = tmp_path / ".tmux.conf"
        tmux_conf.write_text("set -g mouse on\n")

        with (
            patch("studyloop.doctor.config.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.doctor.config.Path.home", return_value=tmp_path),
        ):
            results = check_tmux_resurrect()

        assert len(results) == 1
        assert results[0].status == "warn"
        assert "resurrect" in results[0].message.lower()

    def test_resurrect_with_hook_passes(self, tmp_path: Path):
        from studyloop.doctor.config import check_tmux_resurrect

        # Create resurrect plugin dir
        plugin_dir = tmp_path / ".tmux" / "plugins" / "tmux-resurrect"
        plugin_dir.mkdir(parents=True)
        # Create tmux.conf WITH the restore hook
        tmux_conf = tmp_path / ".tmux.conf"
        tmux_conf.write_text(
            "set -g @resurrect-restore-hook "
            '\'for s in $(tmux list-sessions -F "#{session_name}" '
            '2>/dev/null | grep "^study-"); do '
            'tmux kill-session -t "$s" 2>/dev/null; done\'\n'
        )

        with (
            patch("studyloop.doctor.config.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.doctor.config.Path.home", return_value=tmp_path),
        ):
            results = check_tmux_resurrect()

        assert len(results) == 1
        assert results[0].status == "pass"
        assert "configured" in results[0].message


# ---------------------------------------------------------------------------
# check_obsidian_vault — .obsidian/ marker check (extended behaviour)
# ---------------------------------------------------------------------------


class TestObsidianVaultMarkerCheck:
    """check_obsidian_vault must warn when the dir exists but .obsidian/ is absent."""

    def test_vault_dir_without_obsidian_marker_warns(self, tmp_path: Path):
        """A plain directory without .obsidian/ produces a warn result."""
        from studyloop.doctor.config import check_obsidian_vault

        bare = tmp_path / "bare_vault"
        bare.mkdir()
        # No .obsidian/ inside

        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(bare)),
        ):
            results = check_obsidian_vault()

        assert results[0].status == "warn"
        assert ".obsidian" in results[0].message

    def test_vault_dir_with_obsidian_marker_passes(self, tmp_path: Path):
        """A directory WITH .obsidian/ produces a pass result (existing behaviour preserved)."""
        from studyloop.doctor.config import check_obsidian_vault

        vault = tmp_path / "proper_vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(obsidian_base=str(vault)),
        ):
            results = check_obsidian_vault()

        assert results[0].status == "pass"


# ---------------------------------------------------------------------------
# check_obsidian_export
# ---------------------------------------------------------------------------


class TestCheckObsidianExport:
    """Tests for the new check_obsidian_export() doctor check."""

    def test_returns_info_when_export_disabled(self, tmp_path: Path):
        """When export_enabled is False, returns info status."""
        from studyloop.doctor.config import check_obsidian_export

        obs_cfg = _make_obsidian_config(
            export_enabled=False,
            vault_path=str(tmp_path / "vault"),
        )
        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(
                obsidian_base=str(tmp_path / "vault"),
                obsidian=obs_cfg,
            ),
        ):
            results = check_obsidian_export()

        assert len(results) == 1
        assert results[0].status == "info"
        assert "disabled" in results[0].message.lower()

    def test_returns_pass_when_export_enabled_and_vault_exists(self, tmp_path: Path):
        """When export_enabled is True and vault_path exists, returns pass."""
        from studyloop.doctor.config import check_obsidian_export

        vault = tmp_path / "vault"
        vault.mkdir()
        obs_cfg = _make_obsidian_config(
            export_enabled=True,
            vault_path=str(vault),
            memory_dir="AgentMemory",
        )
        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(
                obsidian_base=str(vault),
                obsidian=obs_cfg,
            ),
        ):
            results = check_obsidian_export()

        assert len(results) == 1
        assert results[0].status == "pass"

    def test_returns_warn_when_export_enabled_and_vault_missing(self, tmp_path: Path):
        """When export_enabled is True but vault_path does not exist, returns warn."""
        from studyloop.doctor.config import check_obsidian_export

        missing_vault = tmp_path / "nonexistent"
        obs_cfg = _make_obsidian_config(
            export_enabled=True,
            vault_path=str(missing_vault),
            memory_dir="AgentMemory",
        )
        with patch(
            "studyloop.doctor.config._load_settings",
            return_value=_make_settings(
                obsidian_base=str(missing_vault),
                obsidian=obs_cfg,
            ),
        ):
            results = check_obsidian_export()

        assert len(results) == 1
        assert results[0].status == "warn"
        assert str(missing_vault) in results[0].message
