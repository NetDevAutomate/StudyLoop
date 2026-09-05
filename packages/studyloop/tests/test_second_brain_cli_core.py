"""T1 C10: the exact JSON ``studyloop brain status`` prints.

Pinned as an exact key set rather than "contains these keys" because an agent
parses this: a field quietly added is a field the wind-down protocol might start
branching on without anyone deciding it should, and a field quietly removed
breaks the protocol silently.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

import studyloop.settings as settings
from studyloop.cli import cli
from studyloop.cli._brain import brain_group

STATUS_KEYS = {
    "provider",
    "configured",
    "available",
    "supports_publish",
    "supports_pull_notes",
    "vault_path",
    "folder",
    "detail",
}


@pytest.fixture()
def config(tmp_path, monkeypatch):
    def _write(mapping: dict):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(mapping))
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
        return path

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(tmp_path / "plans"))
    return _write


def _status(args=("status", "--json")) -> dict:
    result = CliRunner().invoke(brain_group, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_status_json_disabled_shape(config) -> None:
    config({"topics": []})
    assert _status() == {
        "provider": "none",
        "configured": False,
        "available": False,
        "supports_publish": False,
        "supports_pull_notes": False,
        "vault_path": None,
        "folder": None,
        "detail": "Second brain is not configured.",
    }


def test_status_json_xtiles_stage_one_shape(config) -> None:
    config({"second_brain": {"provider": "xtiles"}})
    payload = _status()
    assert set(payload) == STATUS_KEYS
    assert payload["provider"] == "xtiles"
    assert payload["configured"] is True
    assert payload["supports_publish"] is False
    assert payload["vault_path"] is None


def test_status_json_obsidian_shape(config, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config({"second_brain": {"provider": "obsidian", "vault_path": str(vault)}})
    payload = _status()
    assert set(payload) == STATUS_KEYS
    assert payload["provider"] == "obsidian"
    assert payload["configured"] is True
    assert payload["available"] is True
    assert payload["supports_publish"] is True
    assert payload["folder"] == "Study"
    assert payload["vault_path"] == str(vault)


def test_status_reports_a_missing_vault_without_failing(config, tmp_path) -> None:
    """A vault on an unmounted drive is a diagnosis, not a crash."""
    config({"second_brain": {"provider": "obsidian", "vault_path": str(tmp_path / "gone")}})
    payload = _status()
    assert payload["configured"] is True
    assert payload["available"] is False
    assert "gone" in payload["detail"]


def test_status_human_lines(config, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config({"second_brain": {"provider": "obsidian", "vault_path": str(vault)}})
    result = CliRunner().invoke(brain_group, ["status"])
    assert result.exit_code == 0
    for field in ("provider", "configured", "available", "folder"):
        assert field in result.output


def test_publish_disabled_exits_zero_with_skipped_json(config) -> None:
    """Disabled is a state, not an error.

    Exit 1 here would make ``studyloop brain publish`` unusable in any script or
    agent protocol that runs it unconditionally.
    """
    config({"second_brain": {"provider": "none"}})
    result = CliRunner().invoke(brain_group, ["publish", "--plan", "anything", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["provider"] == "none"
    assert payload["dry_run"] is False
    assert payload["operations"][0]["written"] == []
    assert payload["operations"][0]["skipped"] == ["Second brain is not configured."]


def test_publish_reports_a_backend_error_as_one_line(config, tmp_path) -> None:
    """``SecondBrainError`` becomes a message and exit 1, never a traceback."""
    vault = tmp_path / "vault"
    vault.mkdir()
    config({"second_brain": {"provider": "obsidian", "vault_path": str(vault)}})
    result = CliRunner().invoke(brain_group, ["publish", "--plan", "python-decorators"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_destination_set_retains_url_without_selecting_provider(config) -> None:
    config_path = config({"topics": []})
    destination = "https://app.xtiles.app/doc/private-study-plan"

    result = CliRunner().invoke(
        brain_group,
        [
            "destination",
            "set",
            "--provider",
            "xtiles",
            "--url",
            destination,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "provider": "none",
        "configured": True,
        "config_path": str(config_path),
    }
    assert destination not in result.output
    raw = yaml.safe_load(config_path.read_text())
    assert raw["second_brain"]["xtiles_destination_url"] == destination
    assert raw["second_brain"].get("provider", "none") == "none"


def test_destination_set_human_output_reports_only_reviewed_host(config) -> None:
    config({"second_brain": {"provider": "none"}})
    destination = "https://app.xtiles.app/doc/private-study-plan"

    result = CliRunner().invoke(
        brain_group,
        [
            "destination",
            "set",
            "--provider",
            "xtiles",
            "--url",
            destination,
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Configured xTiles destination: app.xtiles.app" in result.output
    assert destination not in result.output
    assert "/doc/private-study-plan" not in result.output


def test_destination_clear_leaves_selected_provider_unchanged(config) -> None:
    destination = "https://xtiles.app/projects/private-study-plan"
    config_path = config(
        {
            "second_brain": {
                "provider": "xtiles",
                "xtiles_destination_url": destination,
            }
        }
    )

    result = CliRunner().invoke(
        brain_group,
        ["destination", "clear", "--provider", "xtiles", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "provider": "xtiles",
        "configured": False,
        "config_path": str(config_path),
    }
    assert destination not in result.output
    raw = yaml.safe_load(config_path.read_text())
    assert raw["second_brain"] == {"provider": "xtiles"}


def test_enable_uses_shared_mutation_owner_and_keeps_destination_redacted(
    config, monkeypatch
) -> None:
    destination = "https://xtiles.app/projects/private-study-plan"
    config(
        {
            "unrelated": "kept",
            "second_brain": {"xtiles_destination_url": destination},
        }
    )
    real_mutate = settings.mutate_raw_config
    mutation_count = 0

    def track_mutation(mutator):
        nonlocal mutation_count
        mutation_count += 1
        return real_mutate(mutator)

    monkeypatch.setattr(settings, "mutate_raw_config", track_mutation)

    result = CliRunner().invoke(brain_group, ["enable", "xtiles", "--json"])

    assert result.exit_code == 0, result.output
    assert mutation_count == 1
    assert destination not in result.output
    raw = settings.load_raw_config()
    assert raw["unrelated"] == "kept"
    assert raw["second_brain"] == {
        "provider": "xtiles",
        "xtiles_destination_url": destination,
    }


def test_destination_commands_are_discoverable_from_public_cli() -> None:
    group_result = CliRunner().invoke(cli, ["brain", "destination", "--help"])
    set_result = CliRunner().invoke(cli, ["brain", "destination", "set", "--help"])
    clear_result = CliRunner().invoke(cli, ["brain", "destination", "clear", "--help"])

    assert group_result.exit_code == 0, group_result.output
    assert set_result.exit_code == 0, set_result.output
    assert clear_result.exit_code == 0, clear_result.output
