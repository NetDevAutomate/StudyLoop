"""T1 C9: backend selection, and what ``provider: xtiles`` means.

xTiles is the interesting case. It is *configured* — the learner chose it — but
StudyLoop has no programmatic path to it: the learner's assistant talks to
xTiles' own MCP connector. Reporting ``configured=True`` with
``supports_publish=False`` is what lets the wind-down protocol stay silent
instead of offering a command that cannot work, while ``doctor`` can still
confirm the choice was understood.
"""

from __future__ import annotations

import sys

import pytest

from studyloop.second_brain import get_backend
from studyloop.second_brain.core import (
    XTILES_STAGE_ONE_DETAIL,
    NullBackend,
    PublishResult,
    SecondBrain,
    XtilesStageOneBackend,
)
from studyloop.settings import ConfigError, SecondBrainConfig, Settings


def _settings(**overrides) -> Settings:
    settings = Settings()
    settings.second_brain = SecondBrainConfig(**overrides)
    return settings


def test_none_selects_the_null_backend() -> None:
    assert isinstance(get_backend(_settings(provider="none")), NullBackend)


def test_obsidian_selects_the_obsidian_backend(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    backend = get_backend(_settings(provider="obsidian", vault_path=vault))
    assert isinstance(backend, SecondBrain)
    assert backend.describe().provider == "obsidian"
    assert backend.describe().vault_path == str(vault)


def test_xtiles_is_configured_but_programmatically_unavailable() -> None:
    backend = get_backend(_settings(provider="xtiles"))
    assert isinstance(backend, XtilesStageOneBackend)
    description = backend.describe()
    assert description.configured is True
    assert description.available is False
    assert description.supports_publish is False
    assert description.supports_pull_notes is False
    assert description.detail == XTILES_STAGE_ONE_DETAIL


def test_xtiles_operations_return_skipped_results() -> None:
    """Never raise: a learner on xTiles running a publish should be told why,
    not handed an error that looks like a bug."""
    backend = get_backend(_settings(provider="xtiles"))
    for result in (
        backend.publish_plan("python-decorators"),
        backend.publish_today(),
        backend.publish_learning_record("python-decorators", 1),
    ):
        assert isinstance(result, PublishResult)
        assert result.provider == "xtiles"
        assert result.written == ()
        assert result.skipped == (XTILES_STAGE_ONE_DETAIL,)
    assert backend.pull_notes("python-decorators").found is False


def test_xtiles_selection_imports_no_api_client() -> None:
    """Stage 1 has no client, no token and no secrets-store entry.

    The assertion is on ``sys.modules`` rather than on source text because the
    thing that must not happen is an import at runtime, not a string in a file.

    Scoped to ``studyloop.`` modules on purpose. The first version searched the
    whole of ``sys.modules`` for the substring, which passed only for as long as
    nothing else in the process happened to have "xtiles" in its name — then
    `test_xtiles_journey.py` and `test_xtiles_live.py` were added and the assertion
    started failing in the full suite while still passing on its own. The property
    is about what StudyLoop imports; a test module's own name is not evidence of
    anything.
    """
    for name in list(sys.modules):
        if name.startswith("studyloop.second_brain.obsidian"):
            del sys.modules[name]
    get_backend(_settings(provider="xtiles")).describe()
    assert not [
        name for name in sys.modules if name.startswith("studyloop.") and "xtiles" in name.lower()
    ]
    assert "studyloop.second_brain.obsidian" not in sys.modules


def test_an_unknown_provider_on_a_hand_built_settings_is_a_config_error() -> None:
    """``load_settings`` validates the provider, but a hand-built ``Settings``
    never passes through it. Returning ``NullBackend`` for a typo would present
    "off" as success."""
    with pytest.raises(ConfigError, match=r"second_brain\.provider"):
        get_backend(_settings(provider="notion"))


def test_get_backend_reads_settings_when_none_is_passed(tmp_path, monkeypatch) -> None:
    import yaml

    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump({"second_brain": {"provider": "xtiles"}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    assert isinstance(get_backend(), XtilesStageOneBackend)
