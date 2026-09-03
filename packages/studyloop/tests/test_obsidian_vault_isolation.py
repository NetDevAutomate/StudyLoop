"""T1 step 7 / clause 10: the learner's real vault is unreachable from the suite.

This must be green BEFORE any test can drive code that writes into a vault.
Everything else in the second-brain layer is reviewable by reading a diff; a
test that reaches the real vault is not — it corrupts notes the learner wrote by
hand, and the damage is only visible later.

Three layers are asserted here; the session-finish hook in ``conftest.py`` is the
fourth, and it fails the whole run if the watched folder changed however the
change got there.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from _vault_isolation import (
    REAL_VAULT_WATCHED_NAMES,
    VAULT_ENV,
    is_under_real_home,
)

from studyloop.settings import SECOND_BRAIN_VAULT_ENV, SecondBrainConfig, load_settings


def test_the_settings_module_and_the_suite_agree_on_the_override_name() -> None:
    """One typo here would silently disable the whole isolation layer."""
    assert SECOND_BRAIN_VAULT_ENV == VAULT_ENV


def test_real_default_vault_is_unreachable() -> None:
    """Neither resolution path may land inside the learner's real home.

    Both are checked because they are independent: ``load_settings`` walks the
    config's resolution chain — which can fall back to ``obsidian_base``, whose
    default IS the real vault, read from the learner's REAL ``config.yaml``
    whenever ``STUDYLOOP_CONFIG`` is unset — while a directly constructed config
    uses the dataclass default factory. Covering one leaves the other open.
    """
    assert not is_under_real_home(load_settings().second_brain.vault_path)
    assert not is_under_real_home(SecondBrainConfig().vault_path)


def test_the_isolation_override_is_set_for_every_test() -> None:
    """The env var is the layer that survives a subprocess boundary.

    A CLI test that shells out inherits the environment and nothing else, so if
    this is unset the isolation covers in-process callers only — which is how
    earlier incidents in this repo reached the learner's real state directory.
    """
    override = os.environ.get(VAULT_ENV, "")
    assert override, f"{VAULT_ENV} must be set for the whole suite"
    assert not is_under_real_home(Path(override))


def test_an_explicit_configured_vault_still_wins_over_the_override(tmp_path, monkeypatch) -> None:
    """Isolation must not defeat a test that deliberately names its own vault.

    The Obsidian backend suite writes into a ``tmp_path`` vault named in config,
    so the override sits ABOVE the legacy fallbacks and BELOW an explicit
    ``second_brain.vault_path``.
    """
    chosen = tmp_path / "chosen-vault"
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.dump({"second_brain": {"provider": "obsidian", "vault_path": str(chosen)}})
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    from studyloop import settings as settings_mod

    assert settings_mod.load_settings().second_brain.vault_path == chosen


def test_the_watch_list_is_scoped_to_the_studyloop_folder() -> None:
    """The guard watches one named folder, and that is deliberate.

    Watching the whole vault would fail runs for reasons that have nothing to do
    with StudyLoop — Obsidian rewrites its own workspace file while the suite
    runs, and a synced vault changes under the developer's feet. A guard that
    cries wolf is a guard developers learn to ignore.
    """
    assert REAL_VAULT_WATCHED_NAMES == ("Study",)
