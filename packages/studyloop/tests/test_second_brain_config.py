"""T1 C3/C4/C5/C12: parsing and validating the ``second_brain`` config section.

Two themes run through these tests.

*Nothing implies consent.* A learner who configured an Obsidian vault years ago
for the session-memory export has not asked StudyLoop to start writing study
notes into it. So every legacy key is readable as a vault LOCATION and none of
them may switch the provider on.

*A typo must be loud.* An unknown provider, or a key retired with the withdrawn
CLI adapter, silently falling back to "off" is the worst outcome: the learner
believes they opted in, nothing is ever written, and there is no signal. Each one
is a one-line ``ConfigError`` instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from studyloop.settings import ConfigError, SecondBrainConfig, load_settings


@pytest.fixture()
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a config.yaml and point ``STUDYLOOP_CONFIG`` at it."""
    path = tmp_path / "config.yaml"

    def _write(mapping: dict) -> Path:
        path.write_text(yaml.dump(mapping, default_flow_style=False, sort_keys=False))
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
        return path

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
    return _write


@pytest.fixture()
def without_vault_isolation(monkeypatch: pytest.MonkeyPatch):
    """Clear the test-isolation vault override.

    The override deliberately outranks the LEGACY resolution fallbacks
    (``obsidian.vault_path``, ``obsidian_base``) so that a test which does not
    name a vault can never be handed the learner's real one. A test that is
    specifically about those fallbacks therefore has to stand the override down
    — and must name a ``tmp_path`` vault itself, which every user of this
    fixture does.
    """
    from studyloop.settings import SECOND_BRAIN_VAULT_ENV

    monkeypatch.delenv(SECOND_BRAIN_VAULT_ENV, raising=False)


# ---------------------------------------------------------------------------
# C3 — absence means off, and no legacy key changes that
# ---------------------------------------------------------------------------


def test_absent_section_defaults_to_none(config_file) -> None:
    config_file({"obsidian_base": "~/Obsidian"})
    assert load_settings().second_brain.provider == "none"


def test_no_config_file_at_all_defaults_to_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "missing.yaml"))
    assert load_settings().second_brain.provider == "none"


def test_legacy_obsidian_path_does_not_enable_provider(config_file, tmp_path) -> None:
    config_file({"obsidian": {"vault_path": str(tmp_path / "vault")}})
    assert load_settings().second_brain.provider == "none"


def test_obsidian_export_config_does_not_enable_provider(config_file, tmp_path) -> None:
    config_file({"obsidian": {"export_enabled": True, "vault_path": str(tmp_path / "vault")}})
    assert load_settings().second_brain.provider == "none"


# ---------------------------------------------------------------------------
# C4 — vault_path resolution order, decided from RAW keys
# ---------------------------------------------------------------------------


def test_explicit_second_brain_vault_wins(config_file, tmp_path) -> None:
    config_file(
        {
            "obsidian_base": str(tmp_path / "legacy-base"),
            "obsidian": {"vault_path": str(tmp_path / "export-vault")},
            "second_brain": {"provider": "obsidian", "vault_path": str(tmp_path / "chosen")},
        }
    )
    assert load_settings().second_brain.vault_path == tmp_path / "chosen"


def test_explicit_obsidian_export_vault_is_fallback(
    config_file, tmp_path, without_vault_isolation
) -> None:
    config_file(
        {
            "obsidian_base": str(tmp_path / "legacy-base"),
            "obsidian": {"vault_path": str(tmp_path / "export-vault")},
            "second_brain": {"provider": "obsidian"},
        }
    )
    assert load_settings().second_brain.vault_path == tmp_path / "export-vault"


def test_obsidian_base_is_legacy_fallback(config_file, tmp_path, without_vault_isolation) -> None:
    config_file(
        {
            "obsidian_base": str(tmp_path / "legacy-base"),
            "second_brain": {"provider": "obsidian"},
        }
    )
    assert load_settings().second_brain.vault_path == tmp_path / "legacy-base"


def test_resolution_reads_raw_keys_not_dataclass_defaults(
    config_file, tmp_path, without_vault_isolation
) -> None:
    """A bare ``obsidian:`` section must not out-rank ``obsidian_base``.

    ``ObsidianConfig.vault_path`` has a default, so asking the dataclass "was a
    vault configured?" always answers yes. Presence has to be decided from the
    raw mapping or the legacy fallback is unreachable.
    """
    config_file(
        {
            "obsidian_base": str(tmp_path / "legacy-base"),
            "obsidian": {"export_enabled": False},
            "second_brain": {"provider": "obsidian"},
        }
    )
    assert load_settings().second_brain.vault_path == tmp_path / "legacy-base"


def test_directly_constructed_config_keeps_the_dataclass_default(monkeypatch) -> None:
    """``SecondBrainConfig()`` is legitimate; it must not need a config file.

    Asserted against the env override rather than a literal ``~/Obsidian/Personal``,
    because the suite's own vault isolation sets that override for every test —
    which is exactly the behaviour that makes the real vault unreachable.
    """
    from studyloop.settings import SECOND_BRAIN_VAULT_ENV

    monkeypatch.setenv(SECOND_BRAIN_VAULT_ENV, "/nonexistent/isolated-vault")
    assert SecondBrainConfig().vault_path == Path("/nonexistent/isolated-vault")
    assert SecondBrainConfig().provider == "none"
    assert SecondBrainConfig().folder == "Study"

    monkeypatch.delenv(SECOND_BRAIN_VAULT_ENV, raising=False)
    assert SecondBrainConfig().vault_path == Path.home() / "Obsidian" / "Personal"


# ---------------------------------------------------------------------------
# C5 — validation
# ---------------------------------------------------------------------------


def test_defaults_of_every_field(config_file) -> None:
    config_file({"second_brain": {"provider": "obsidian"}})
    config = load_settings().second_brain
    assert config.folder == "Study"
    assert config.backlinks is True


@pytest.mark.parametrize("key", ["use_cli", "vault_name", "template", "daily_note"])
def test_a_retired_cli_adapter_key_is_reported_not_ignored(config_file, key) -> None:
    """The Obsidian CLI adapter was withdrawn before release; its keys must be loud.

    Silently dropping `daily_note: true` would leave a learner believing StudyLoop
    was still appending a line to their own daily note. There is nothing to migrate --
    the file writer always produced the final bytes -- so naming the key and saying it
    is gone is the whole of the fix.
    """
    config_file({"second_brain": {"provider": "obsidian", key: True}})
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert key in str(excinfo.value)
    assert "withdrawn" in str(excinfo.value)


def test_invalid_provider_is_config_error(config_file) -> None:
    config_file({"second_brain": {"provider": "obsidan"}})
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "second_brain.provider" in message
    assert "none, obsidian, xtiles" in message
    assert "\n" not in message.strip()


def test_absolute_folder_is_config_error(config_file) -> None:
    config_file({"second_brain": {"provider": "obsidian", "folder": "/etc"}})
    with pytest.raises(ConfigError, match=r"second_brain\.folder"):
        load_settings()


def test_parent_traversal_folder_is_config_error(config_file) -> None:
    config_file({"second_brain": {"provider": "obsidian", "folder": "../elsewhere"}})
    with pytest.raises(ConfigError, match=r"second_brain\.folder"):
        load_settings()


def test_empty_folder_is_config_error(config_file) -> None:
    config_file({"second_brain": {"provider": "obsidian", "folder": "   "}})
    with pytest.raises(ConfigError, match=r"second_brain\.folder"):
        load_settings()


def test_non_boolean_flag_is_config_error(config_file) -> None:
    """``backlinks: maybe`` must not be coerced to ``True`` by truthiness."""
    config_file({"second_brain": {"provider": "obsidian", "backlinks": "maybe"}})
    with pytest.raises(ConfigError, match=r"second_brain\.backlinks"):
        load_settings()


def test_non_mapping_section_is_config_error(config_file) -> None:
    config_file({"second_brain": "obsidian"})
    with pytest.raises(ConfigError, match="second_brain"):
        load_settings()


def test_second_brain_counts_as_a_known_top_level_key(config_file) -> None:
    from studyloop.settings import known_top_level_keys, unknown_top_level_keys

    assert "second_brain" in known_top_level_keys()
    config_file({"second_brain": {"provider": "none"}})
    assert unknown_top_level_keys() == []


def test_invalid_config_cli_output_is_one_line(config_file) -> None:
    """``ConfigError`` is a ClickException, so the CLI prints one line, not a
    traceback. Proven through the runner, not by reading the class."""
    from studyloop.cli._config import config_group

    config_file({"second_brain": {"provider": "obsidan"}})
    result = CliRunner().invoke(config_group, ["show"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "second_brain.provider" in result.output


# ---------------------------------------------------------------------------
# C12 — no environment variable selects a provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "STUDYLOOP_SECOND_BRAIN",
        "STUDYLOOP_SECOND_BRAIN_PROVIDER",
        "STUDYLOOP_BRAIN_PROVIDER",
    ],
)
def test_unrecognised_provider_environment_variable_has_no_effect(
    config_file, monkeypatch, name
) -> None:
    """Selecting a provider authorises writes into the learner's own files, so
    it must be a deliberate config change and never an inherited variable."""
    config_file({})
    monkeypatch.setenv(name, "obsidian")
    assert load_settings().second_brain.provider == "none"
