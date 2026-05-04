"""Tests for load_settings() — covers scalar fields, sub-configs, and edge cases."""

from pathlib import Path
from unittest.mock import patch

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def _load(config_path):
    from studyctl.settings import load_settings

    with patch("studyctl.settings._CONFIG_PATH", config_path):
        return load_settings()


# ---------------------------------------------------------------------------
# Defaults (no config file)
# ---------------------------------------------------------------------------


def test_defaults_when_no_config_file(tmp_path):
    missing = tmp_path / "does-not-exist.yaml"
    with patch("studyctl.settings._CONFIG_PATH", missing):
        from studyctl.settings import load_settings

        s = load_settings()

    assert s.ttyd_port == 7681
    assert s.web_port == 8567
    assert s.browser == ""
    assert s.topics == []
    assert s.agents.custom == {}


def test_get_config_path_honors_env_lazily(monkeypatch, tmp_path):
    from studyctl.settings import get_config_path

    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    monkeypatch.setenv("STUDYCTL_CONFIG", str(first))
    assert get_config_path() == first

    monkeypatch.setenv("STUDYCTL_CONFIG", str(second))
    assert get_config_path() == second


def test_load_raw_config_reads_env_override(monkeypatch, tmp_path):
    from studyctl.settings import load_raw_config

    config_path = tmp_path / "custom.yaml"
    config_path.write_text("browser: firefox\n")
    monkeypatch.setenv("STUDYCTL_CONFIG", str(config_path))

    assert load_raw_config() == {"browser": "firefox"}


def test_write_raw_config_creates_parent_and_round_trips(monkeypatch, tmp_path):
    from studyctl.settings import load_raw_config, write_raw_config

    config_path = tmp_path / "nested" / "config.yaml"
    monkeypatch.setenv("STUDYCTL_CONFIG", str(config_path))

    written_path = write_raw_config({"browser": "brave", "web_port": 9000})

    assert written_path == config_path
    assert load_raw_config() == {"browser": "brave", "web_port": 9000}


def test_load_raw_config_rejects_invalid_yaml(monkeypatch, tmp_path):
    from studyctl.settings import ConfigError, load_raw_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text("browser: [unterminated\n")
    monkeypatch.setenv("STUDYCTL_CONFIG", str(config_path))

    try:
        load_raw_config()
    except ConfigError as exc:
        assert "Invalid YAML" in exc.message
        assert str(config_path) in exc.message
    else:
        raise AssertionError("Expected ConfigError")


def test_load_raw_config_rejects_non_mapping(monkeypatch, tmp_path):
    from studyctl.settings import ConfigError, load_raw_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not\n- a\n- mapping\n")
    monkeypatch.setenv("STUDYCTL_CONFIG", str(config_path))

    try:
        load_raw_config()
    except ConfigError as exc:
        assert "expected a YAML mapping" in exc.message
    else:
        raise AssertionError("Expected ConfigError")


# ---------------------------------------------------------------------------
# Scalar top-level fields (data-driven mapping)
# ---------------------------------------------------------------------------


def test_scalar_path_fields_are_expanded(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": "~/MyVault",
            "session_db": "~/mydb.sqlite",
            "state_dir": "~/mystate",
        },
    )
    s = _load(config_path)

    assert s.obsidian_base == Path.home() / "MyVault"
    assert s.session_db == Path.home() / "mydb.sqlite"
    assert s.state_dir == Path.home() / "mystate"


def test_scalar_int_fields(tmp_path):
    config_path = _write_config(tmp_path, {"ttyd_port": 9999, "web_port": 1234})
    s = _load(config_path)

    assert s.ttyd_port == 9999
    assert s.web_port == 1234


def test_scalar_str_fields(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "sync_remote": "myhost",
            "sync_user": "alice",
            "browser": "firefox",
            "lan_username": "learner",
            "lan_password": "s3cr3t",
        },
    )
    s = _load(config_path)

    assert s.sync_remote == "myhost"
    assert s.sync_user == "alice"
    assert s.browser == "firefox"
    assert s.lan_username == "learner"
    assert s.lan_password == "s3cr3t"


def test_absent_scalar_fields_keep_defaults(tmp_path):
    # Only set one field; others should remain at dataclass defaults.
    config_path = _write_config(tmp_path, {"browser": "chrome"})
    s = _load(config_path)

    assert s.browser == "chrome"
    assert s.ttyd_port == 7681  # unchanged default
    assert s.web_port == 8567  # unchanged default


# ---------------------------------------------------------------------------
# Topics (bespoke path resolution)
# ---------------------------------------------------------------------------


def test_topic_relative_path_resolved_against_obsidian_base(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(tmp_path / "vault"),
            "topics": [
                {"name": "Python", "slug": "python", "obsidian_path": "Study/Python"},
            ],
        },
    )
    s = _load(config_path)

    assert len(s.topics) == 1
    assert s.topics[0].obsidian_path == tmp_path / "vault" / "Study/Python"


def test_topic_absolute_path_not_rebased(tmp_path):
    abs_path = str(tmp_path / "absolute" / "Python")
    config_path = _write_config(
        tmp_path,
        {
            "topics": [
                {"name": "Python", "slug": "python", "obsidian_path": abs_path},
            ],
        },
    )
    s = _load(config_path)

    assert s.topics[0].obsidian_path == Path(abs_path)


def test_topic_optional_fields_have_defaults(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "topics": [
                {"name": "SQL", "slug": "sql", "obsidian_path": "Study/SQL"},
            ],
        },
    )
    s = _load(config_path)

    assert s.topics[0].notebook_id == ""
    assert s.topics[0].tags == []


# ---------------------------------------------------------------------------
# NotebookLM config
# ---------------------------------------------------------------------------


def test_notebooklm_enabled_parsed(tmp_path):
    config_path = _write_config(tmp_path, {"notebooklm": {"enabled": True}})
    s = _load(config_path)
    assert s.notebooklm.enabled is True


def test_notebooklm_absent_keeps_default(tmp_path):
    config_path = _write_config(tmp_path, {"browser": "safari"})
    s = _load(config_path)
    assert s.notebooklm.enabled is False


# ---------------------------------------------------------------------------
# Pomodoro config
# ---------------------------------------------------------------------------


def test_pomodoro_fields_parsed(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"pomodoro": {"focus": 50, "short_break": 10, "long_break": 30, "cycles": 3}},
    )
    s = _load(config_path)

    assert s.pomodoro.focus == 50
    assert s.pomodoro.short_break == 10
    assert s.pomodoro.long_break == 30
    assert s.pomodoro.cycles == 3


def test_pomodoro_partial_override_uses_defaults_for_missing(tmp_path):
    config_path = _write_config(tmp_path, {"pomodoro": {"focus": 45}})
    s = _load(config_path)

    assert s.pomodoro.focus == 45
    assert s.pomodoro.short_break == 5  # default
    assert s.pomodoro.long_break == 15  # default
    assert s.pomodoro.cycles == 4  # default


# ---------------------------------------------------------------------------
# Content config
# ---------------------------------------------------------------------------


def test_content_base_path_expanded(tmp_path):
    config_path = _write_config(tmp_path, {"content": {"base_path": "~/courses"}})
    s = _load(config_path)
    assert s.content.base_path == Path.home() / "courses"


def test_content_study_paths_resolve_against_obsidian_base(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(tmp_path / "vault"),
            "content": {"study_paths": ["2-Areas/Study/Python", "~/external-course"]},
        },
    )
    s = _load(config_path)

    assert s.content.study_paths == [
        tmp_path / "vault" / "2-Areas/Study/Python",
        Path.home() / "external-course",
    ]


def test_content_defaults_when_absent(tmp_path):
    config_path = _write_config(tmp_path, {"browser": "brave"})
    s = _load(config_path)

    assert s.content.base_path == Path.home() / "study-materials"
    assert s.content.study_paths == []
    assert s.content.notebooklm_timeout == 900
    assert s.content.pandoc_path == "pandoc"


# ---------------------------------------------------------------------------
# Agents config (including _local_llm helper)
# ---------------------------------------------------------------------------


def test_agents_priority_parsed(tmp_path):
    config_path = _write_config(tmp_path, {"agents": {"priority": ["gemini", "claude"]}})
    s = _load(config_path)
    assert s.agents.priority == ["gemini", "claude"]


def test_agents_default_priority_includes_codex():
    from studyctl.settings import Settings

    s = Settings()
    assert s.agents.priority == [
        "claude",
        "kiro",
        "gemini",
        "opencode",
        "codex",
        "ollama",
        "lmstudio",
    ]


def test_agents_ollama_custom_model(tmp_path):
    config_path = _write_config(
        tmp_path, {"agents": {"ollama": {"model": "llama3", "base_url": "http://gpu:4000"}}}
    )
    s = _load(config_path)
    assert s.agents.ollama.model == "llama3"
    assert s.agents.ollama.base_url == "http://gpu:4000"


def test_agents_ollama_defaults_when_section_omitted(tmp_path):
    # agents: section present but no ollama key — should use built-in defaults.
    config_path = _write_config(tmp_path, {"agents": {"priority": ["claude"]}})
    s = _load(config_path)
    assert s.agents.ollama.model == "qwen3-coder"
    assert s.agents.ollama.base_url == "http://localhost:4000"


def test_agents_lmstudio_defaults_when_section_omitted(tmp_path):
    config_path = _write_config(tmp_path, {"agents": {"priority": ["claude"]}})
    s = _load(config_path)
    assert s.agents.lmstudio.model == "qwen3-coder"
    assert s.agents.lmstudio.base_url == "http://localhost:1234"


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
    config_path = _write_config(tmp_path, config)
    s = _load(config_path)

    assert "aider" in s.agents.custom
    assert s.agents.custom["aider"]["binary"] == "aider"


def test_custom_defaults_to_empty():
    from studyctl.settings import Settings

    s = Settings()
    assert s.agents.custom == {}


# ---------------------------------------------------------------------------
# Knowledge domains
# ---------------------------------------------------------------------------


def test_knowledge_domains_parsed(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "knowledge_domains": {
                "primary": "networking",
                "anchors": [{"concept": "BGP", "comfort": 9}],
                "secondary": [
                    {"domain": "cooking", "anchors": ["mise en place"]},
                ],
            }
        },
    )
    s = _load(config_path)

    assert s.knowledge_domains.primary == "networking"
    assert len(s.knowledge_domains.anchors) == 1
    assert len(s.knowledge_domains.secondary) == 1
    assert s.knowledge_domains.secondary[0].domain == "cooking"
