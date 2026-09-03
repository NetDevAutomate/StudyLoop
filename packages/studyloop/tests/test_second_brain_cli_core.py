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

from studyloop.cli._brain import brain_group

STATUS_KEYS = {
    "provider",
    "configured",
    "available",
    "supports_publish",
    "supports_pull_notes",
    "vault_path",
    "folder",
    "use_cli",
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
        "use_cli": False,
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
