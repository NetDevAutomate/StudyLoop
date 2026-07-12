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
    from studyloop.settings import load_settings

    with patch("studyloop.settings._CONFIG_PATH", config_path):
        return load_settings()


# ---------------------------------------------------------------------------
# Defaults (no config file)
# ---------------------------------------------------------------------------


def test_defaults_when_no_config_file(tmp_path):
    missing = tmp_path / "does-not-exist.yaml"
    with patch("studyloop.settings._CONFIG_PATH", missing):
        from studyloop.settings import load_settings

        s = load_settings()

    assert s.ttyd_port == 7681
    assert s.web_port == 8567
    assert s.browser == ""
    assert s.topics == []
    assert s.content.study_paths == [Path.home() / "Obsidian" / "Personal" / "Study"]
    assert s.agents.custom == {}


def test_get_config_path_honors_env_lazily(monkeypatch, tmp_path):
    from studyloop.settings import get_config_path

    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(first))
    assert get_config_path() == first

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(second))
    assert get_config_path() == second


def test_load_raw_config_reads_env_override(monkeypatch, tmp_path):
    from studyloop.settings import load_raw_config

    config_path = tmp_path / "custom.yaml"
    config_path.write_text("browser: firefox\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    assert load_raw_config() == {"browser": "firefox"}


def test_resolve_study_dirs_uses_explicit_review_directories(monkeypatch, tmp_path):
    # When review.directories is set, it wins verbatim.
    from studyloop.settings import resolve_study_dirs

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "content": {"base_path": str(tmp_path / "study")},
                "review": {"directories": [str(tmp_path / "explicit")]},
            }
        )
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    assert resolve_study_dirs() == [str(tmp_path / "explicit")]


def test_resolve_study_dirs_falls_back_to_content_base_path(monkeypatch, tmp_path):
    # The real bug: review.directories unset → read root must default to the
    # write root (content.base_path) so generated decks are discoverable.
    from studyloop.settings import resolve_study_dirs

    study = tmp_path / "Study"
    study.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"content": {"base_path": str(study)}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    assert resolve_study_dirs() == [str(study)]


def test_resolve_study_dirs_expands_user_in_fallback(monkeypatch, tmp_path):
    from studyloop.settings import resolve_study_dirs

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"content": {"base_path": "~/Obsidian/Personal/Study"}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    resolved = resolve_study_dirs()
    assert resolved == [str(Path.home() / "Obsidian" / "Personal" / "Study")]
    assert "~" not in resolved[0]


def test_resolve_study_dirs_empty_when_nothing_configured(monkeypatch, tmp_path):
    from studyloop.settings import resolve_study_dirs

    missing = tmp_path / "none.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(missing))

    # No config at all → default content.base_path (~/study-materials) is used;
    # resolver always yields exactly one root (never empty), so panels have a
    # root to scan even on a fresh install.
    resolved = resolve_study_dirs()
    assert len(resolved) == 1


def test_write_raw_config_creates_parent_and_round_trips(monkeypatch, tmp_path):
    from studyloop.settings import load_raw_config, write_raw_config

    config_path = tmp_path / "nested" / "config.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    written_path = write_raw_config({"browser": "brave", "web_port": 9000})

    assert written_path == config_path
    assert load_raw_config() == {"browser": "brave", "web_port": 9000}


def test_load_raw_config_rejects_invalid_yaml(monkeypatch, tmp_path):
    from studyloop.settings import ConfigError, load_raw_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text("browser: [unterminated\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    try:
        load_raw_config()
    except ConfigError as exc:
        assert "Invalid YAML" in exc.message
        assert str(config_path) in exc.message
    else:
        raise AssertionError("Expected ConfigError")


def test_load_raw_config_rejects_non_mapping(monkeypatch, tmp_path):
    from studyloop.settings import ConfigError, load_raw_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not\n- a\n- mapping\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

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


def test_legacy_string_topics_are_parsed_and_limited(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(tmp_path / "vault"),
            "topics": ["Python", "SQL", "Data Engineering", "AWS Analytics"],
        },
    )
    s = _load(config_path)

    assert [topic.name for topic in s.topics] == ["Python", "SQL", "Data Engineering"]
    assert [topic.slug for topic in s.topics] == ["python", "sql", "data-engineering"]
    assert s.topics[0].obsidian_path == tmp_path / "vault" / "Personal" / "Study" / "Python"
    assert s.topics[0].tags == ["python"]


def test_legacy_string_topics_use_personal_vault_study_dir(tmp_path):
    vault = tmp_path / "Obsidian" / "Personal"
    (vault / "Study" / "Python").mkdir(parents=True)
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(vault),
            "topics": ["Python"],
        },
    )
    s = _load(config_path)

    assert s.topics[0].obsidian_path == vault / "Study" / "Python"


def test_topics_are_limited_to_three_active_entries(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "topics": [
                {"name": "Python", "slug": "python", "obsidian_path": "Study/Python"},
                {"name": "SQL", "slug": "sql", "obsidian_path": "Study/SQL"},
                {
                    "name": "Data Engineering",
                    "slug": "data-engineering",
                    "obsidian_path": "Study/Data-Engineering",
                },
                {"name": "AWS Analytics", "slug": "aws", "obsidian_path": "Study/AWS"},
            ],
        },
    )
    s = _load(config_path)

    assert [topic.slug for topic in s.topics] == ["python", "sql", "data-engineering"]


def test_default_config_keeps_active_topics_to_three():
    from studyloop.settings import MAX_ACTIVE_TOPICS, generate_default_config

    parsed = yaml.safe_load(generate_default_config())

    assert len(parsed["topics"]) == MAX_ACTIVE_TOPICS


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
    assert s.content.study_paths == [Path.home() / "Obsidian" / "Personal" / "Study"]
    assert s.content.notebooklm_timeout == 900
    assert s.content.pandoc_path == "pandoc"


# ---------------------------------------------------------------------------
# Agents config (including _local_llm helper)
# ---------------------------------------------------------------------------


def test_agents_priority_parsed(tmp_path):
    config_path = _write_config(tmp_path, {"agents": {"priority": ["gemini", "claude"]}})
    s = _load(config_path)
    assert s.agents.priority == ["gemini", "claude"]


def test_agents_default_priority_includes_codex_and_grok():
    from studyloop.settings import Settings

    s = Settings()
    assert s.agents.priority == [
        "claude",
        "kiro",
        "gemini",
        "opencode",
        "codex",
        "grok",
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
    from studyloop.settings import Settings

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


# ---------------------------------------------------------------------------
# ObsidianConfig (obsidian: section)
# ---------------------------------------------------------------------------


def test_obsidian_section_fully_parsed(tmp_path):
    """All keys in the obsidian: section are loaded into ObsidianConfig."""
    config_path = _write_config(
        tmp_path,
        {
            "obsidian": {
                "export_enabled": True,
                "vault_path": str(tmp_path / "vault"),
                "memory_dir": "AgentMemory",
                "moc_dir": "AgentMemory/MOC",
                "backlinks": True,
                "granularity": "both",
            }
        },
    )
    s = _load(config_path)

    assert s.obsidian.export_enabled is True
    assert s.obsidian.vault_path == tmp_path / "vault"
    assert s.obsidian.memory_dir == "AgentMemory"
    assert s.obsidian.moc_dir == "AgentMemory/MOC"
    assert s.obsidian.backlinks is True
    assert s.obsidian.granularity == "both"


def test_obsidian_export_disabled_by_default(tmp_path):
    """export_enabled defaults to False when the section is absent."""
    config_path = _write_config(tmp_path, {"browser": "safari"})
    s = _load(config_path)
    assert s.obsidian.export_enabled is False


def test_obsidian_vault_path_defaults_to_obsidian_base_when_absent(tmp_path):
    """vault_path falls back to obsidian_base when not given in the obsidian: section."""
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(tmp_path / "MyVault"),
            "obsidian": {"export_enabled": False},
        },
    )
    s = _load(config_path)
    assert s.obsidian.vault_path == tmp_path / "MyVault"


def test_obsidian_vault_path_defaults_to_obsidian_base_when_no_section(tmp_path):
    """vault_path is aligned with obsidian_base even when the obsidian: section is missing."""
    config_path = _write_config(
        tmp_path,
        {"obsidian_base": str(tmp_path / "MyVault")},
    )
    s = _load(config_path)
    assert s.obsidian.vault_path == tmp_path / "MyVault"


def test_obsidian_vault_path_explicit_wins_over_obsidian_base(tmp_path):
    """An explicit vault_path in the obsidian: section overrides obsidian_base."""
    config_path = _write_config(
        tmp_path,
        {
            "obsidian_base": str(tmp_path / "Base"),
            "obsidian": {
                "export_enabled": True,
                "vault_path": str(tmp_path / "Override"),
            },
        },
    )
    s = _load(config_path)
    assert s.obsidian.vault_path == tmp_path / "Override"


def test_obsidian_vault_path_tilde_expanded(tmp_path):
    """vault_path with ~ is expanded to an absolute path."""
    config_path = _write_config(
        tmp_path,
        {"obsidian": {"vault_path": "~/SomeVault"}},
    )
    s = _load(config_path)
    assert s.obsidian.vault_path == Path.home() / "SomeVault"


def test_obsidian_section_partial_override_uses_defaults(tmp_path):
    """Partial obsidian: section uses dataclass defaults for missing keys."""
    config_path = _write_config(
        tmp_path,
        {"obsidian": {"export_enabled": True}},
    )
    s = _load(config_path)
    assert s.obsidian.export_enabled is True
    assert s.obsidian.memory_dir == "AgentMemory"
    assert s.obsidian.moc_dir == "AgentMemory/MOC"
    assert s.obsidian.backlinks is True
    assert s.obsidian.granularity == "both"


# ---------------------------------------------------------------------------
# Dotted top-level keys (user-reported: `tts.backend: openvox` at top level)
# ---------------------------------------------------------------------------


def _load_raw(config_path):
    from studyloop.settings import load_raw_config

    with patch("studyloop.settings._CONFIG_PATH", config_path):
        return load_raw_config()


def test_dotted_top_level_key_expands_to_nested(tmp_path):
    """`tts.backend: openvox` at YAML top level must behave as tts: {backend: openvox}.

    The doctor's own repair message used to suggest exactly this flat form,
    so real user configs contain it.
    """
    p = _write_config(tmp_path, {"tts.backend": "openvox"})
    raw = _load_raw(p)
    assert raw.get("tts", {}).get("backend") == "openvox"
    assert "tts.backend" not in raw


def test_nested_tts_key_still_works(tmp_path):
    p = _write_config(tmp_path, {"tts": {"backend": "openvox"}})
    raw = _load_raw(p)
    assert raw["tts"]["backend"] == "openvox"


def test_nested_wins_over_dotted_on_conflict(tmp_path):
    """When both forms are present, the explicit nested mapping is authoritative."""
    p = _write_config(
        tmp_path, {"tts": {"backend": "kokoro"}, "tts.backend": "openvox"}
    )
    raw = _load_raw(p)
    assert raw["tts"]["backend"] == "kokoro"


def test_dotted_key_merges_into_existing_section(tmp_path):
    """A dotted key for a NEW leaf merges into an existing nested section."""
    p = _write_config(
        tmp_path, {"tts": {"voice": "af_bella"}, "tts.backend": "openvox"}
    )
    raw = _load_raw(p)
    assert raw["tts"]["backend"] == "openvox"
    assert raw["tts"]["voice"] == "af_bella"


def test_multi_segment_dotted_key(tmp_path):
    p = _write_config(tmp_path, {"review.export.enabled": True})
    raw = _load_raw(p)
    assert raw["review"]["export"]["enabled"] is True


def test_doctor_voice_honors_flat_tts_backend(tmp_path, monkeypatch):
    """End-to-end: the doctor must see openvox from the flat key (the user's bug)."""
    p = _write_config(tmp_path, {"tts.backend": "openvox"})
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(p))

    from studyloop.doctor.voice import _tts_config

    assert _tts_config().get("backend") == "openvox"


# ---------------------------------------------------------------------------
# Shape-hardening regressions (bare keys, scalar-where-list-expected)
# ---------------------------------------------------------------------------


def _write_raw(tmp_path, text: str, monkeypatch) -> Path:
    """Write literal YAML text (so a bare 'review:' stays None) and point config at it."""
    p = tmp_path / "config.yaml"
    p.write_text(text)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(p))
    return p


def test_resolve_study_dirs_bare_review_key(tmp_path, monkeypatch):
    """A bare 'review:' (parses to None) must not crash resolve_study_dirs."""
    _write_raw(tmp_path, "review:\ncontent:\n  base_path: /tmp/x\n", monkeypatch)
    from studyloop.settings import resolve_study_dirs

    assert resolve_study_dirs() == ["/tmp/x"]


def test_resolve_study_dirs_scalar_directories(tmp_path, monkeypatch):
    """A scalar review.directories must become one dir, not a per-char explosion."""
    _write_raw(
        tmp_path, "review:\n  directories: /tmp/decks\ncontent:\n  base_path: /tmp/x\n", monkeypatch
    )
    from studyloop.settings import resolve_study_dirs

    assert resolve_study_dirs() == ["/tmp/decks"]


def test_scalar_study_paths_not_char_exploded(tmp_path, monkeypatch):
    """A scalar content.study_paths must resolve to one path, not one-per-character."""
    _write_raw(tmp_path, "content:\n  study_paths: /tmp/onepath\n", monkeypatch)
    from studyloop.settings import load_settings

    assert load_settings().content.study_paths == [Path("/tmp/onepath")]


def test_bare_content_key(tmp_path, monkeypatch):
    """A bare 'content:' (None) must not crash load_settings."""
    _write_raw(tmp_path, "content:\n", monkeypatch)
    from studyloop.settings import load_settings

    # Falls back to ContentConfig defaults; the key point is no AttributeError.
    assert load_settings().content.base_path
