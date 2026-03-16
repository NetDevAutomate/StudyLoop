"""Tests for studyctl setup wizard (studyctl setup command).

Uses Click's CliRunner with mocked input to exercise the interactive wizard.
All tests redirect CONFIG_DIR to a tmp_path to avoid touching real user config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner

from studyctl.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def _patch_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect CONFIG_DIR in _setup.py to a temp directory."""
    import studyctl.cli._setup as setup_mod

    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestSetupDefaults:
    def test_setup_exits_zero_with_defaults(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Accepting all defaults completes successfully."""
        # Inputs: materials(Enter), has_ai(y), assistant(Enter=claude-code),
        # notebooklm(Enter=n), obsidian(Enter=y), vault(Enter=~/Obsidian), launch(Enter=n)
        user_input = "\ny\n\nn\ny\n\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)
        assert result.exit_code == 0, result.output

    def test_setup_writes_config_file(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Config file is created when it didn't exist before."""
        config_path = _patch_config_dir / "config.yaml"
        assert not config_path.exists()

        user_input = "\ny\n\nn\ny\n\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)
        assert result.exit_code == 0, result.output
        assert config_path.exists()

    def test_setup_default_materials_path(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Default study-materials path is written to content.base_path."""
        config_path = _patch_config_dir / "config.yaml"

        user_input = "\ny\n\nn\ny\n\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["content"]["base_path"] == "~/study-materials"

    def test_setup_default_obsidian_path(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Default Obsidian vault path ~/Obsidian is written to obsidian_base."""
        config_path = _patch_config_dir / "config.yaml"

        user_input = "\ny\n\nn\ny\n\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["obsidian_base"] == "~/Obsidian"

    def test_setup_notebooklm_disabled_by_default(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """NotebookLM defaults to disabled."""
        config_path = _patch_config_dir / "config.yaml"

        user_input = "\ny\n\nn\ny\n\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["notebooklm"]["enabled"] is False


# ---------------------------------------------------------------------------
# Custom values
# ---------------------------------------------------------------------------


class TestSetupCustomValues:
    def test_custom_materials_path(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Custom study materials path is persisted."""
        config_path = _patch_config_dir / "config.yaml"

        # custom materials path, has_ai=y, claude-code, nlm=n, obsidian=n, launch=n
        user_input = "~/courses\ny\n\nn\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["content"]["base_path"] == "~/courses"

    def test_notebooklm_enabled_when_confirmed(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """NotebookLM is written as enabled when user confirms."""
        config_path = _patch_config_dir / "config.yaml"

        # materials=default, ai=n, nlm=y, obsidian=n, launch=n
        user_input = "\nn\ny\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["notebooklm"]["enabled"] is True

    def test_custom_obsidian_path(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Custom Obsidian vault path is persisted."""
        config_path = _patch_config_dir / "config.yaml"

        # materials=default, ai=n, nlm=n, obsidian=y, custom path, launch=n
        user_input = "\nn\nn\ny\n~/MyVault\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["obsidian_base"] == "~/MyVault"

    def test_ai_assistant_selection(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Selected AI assistant is written to config."""
        config_path = _patch_config_dir / "config.yaml"

        # materials=default, ai=y, kiro, nlm=n, obsidian=n, launch=n
        user_input = "\ny\nkiro\nn\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["ai_assistant"] == "kiro"

    def test_no_ai_assistant(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Declining AI assistant does not write ai_assistant key."""
        config_path = _patch_config_dir / "config.yaml"

        user_input = "\nn\nn\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert "ai_assistant" not in config

    def test_skip_obsidian(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Declining Obsidian integration does not write obsidian_base key."""
        config_path = _patch_config_dir / "config.yaml"

        user_input = "\nn\nn\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert "obsidian_base" not in config


# ---------------------------------------------------------------------------
# Config directory creation
# ---------------------------------------------------------------------------


class TestConfigDirCreation:
    def test_config_dir_is_created(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Config directory is created if it doesn't exist."""
        import studyctl.cli._setup as setup_mod

        nested = tmp_path / "deep" / "nested" / "studyctl"
        assert not nested.exists()
        monkeypatch.setattr(setup_mod, "CONFIG_DIR", nested)

        user_input = "\nn\nn\nn\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)

        assert result.exit_code == 0, result.output
        assert nested.exists()
        assert (nested / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Merge behaviour — existing config is preserved
# ---------------------------------------------------------------------------


class TestSetupMerge:
    def test_existing_keys_preserved(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Keys in an existing config.yaml that the wizard doesn't touch are preserved."""
        config_path = _patch_config_dir / "config.yaml"
        config_path.write_text(
            yaml.dump({"sync_remote": "my-hub", "session_db": "~/.config/studyctl/sessions.db"})
        )

        user_input = "\nn\nn\nn\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["sync_remote"] == "my-hub"
        assert config["session_db"] == "~/.config/studyctl/sessions.db"

    def test_wizard_values_overwrite_existing(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Wizard answers overwrite the same keys from a prior run."""
        config_path = _patch_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"obsidian_base": "~/OldVault"}))

        # materials=default, ai=n, nlm=n, obsidian=y, new path, launch=n
        user_input = "\nn\nn\ny\n~/NewVault\nn\n"
        runner.invoke(cli, ["setup"], input=user_input)

        config = yaml.safe_load(config_path.read_text())
        assert config["obsidian_base"] == "~/NewVault"


# ---------------------------------------------------------------------------
# Output / UX
# ---------------------------------------------------------------------------


class TestSetupOutput:
    def test_banner_shown(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Welcome banner is printed at the start."""
        user_input = "\nn\nn\nn\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)
        assert "studyctl setup" in result.output

    def test_saved_confirmation_shown(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Confirmation message with config path is printed after saving."""
        user_input = "\nn\nn\nn\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)
        assert "Configuration saved" in result.output

    def test_next_steps_shown_when_no_launch(
        self,
        runner: CliRunner,
        _patch_config_dir: Path,
    ) -> None:
        """Next steps are shown when user declines to launch the web UI."""
        user_input = "\nn\nn\nn\nn\n"
        result = runner.invoke(cli, ["setup"], input=user_input)
        assert "studyctl --help" in result.output

    def test_help_text(self, runner: CliRunner) -> None:
        """Help text is accessible."""
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup" in result.output.lower()
