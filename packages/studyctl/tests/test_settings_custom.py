"""Test that custom agents config is parsed."""

from unittest.mock import patch

import yaml


def test_custom_agents_parsed(tmp_path):
    config = {
        "agents": {
            "priority": ["claude"],
            "custom": {
                "aider": {
                    "binary": "aider",
                    "strategy": "cli-flag",
                    "launch": "{binary} --read {persona}",
                }
            },
        }
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))

    with patch("studyctl.settings._CONFIG_PATH", config_path):
        from studyctl.settings import load_settings

        settings = load_settings()

    assert "aider" in settings.agents.custom
    assert settings.agents.custom["aider"]["binary"] == "aider"


def test_custom_defaults_to_empty():
    from studyctl.settings import Settings

    s = Settings()
    assert s.agents.custom == {}
