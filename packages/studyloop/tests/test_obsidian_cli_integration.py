"""Integration check for the installed Obsidian CLI, if there is one.

Marked ``integration`` and skipped unless the binary exists, because the thing it
verifies is an assumption about somebody else's software: that ``obsidian eval``
still accepts the argv shape this repository builds. The unit tests can only
prove that the shape is built correctly; they cannot notice the day the grammar
changes.

Deliberately read-only. It probes and asserts the probe's contract; it never
creates a note, so it can run on a machine whose only vault is the learner's own.
"""

from __future__ import annotations

import shutil

import pytest

pytestmark = pytest.mark.integration


def test_installed_cli_answers_probe() -> None:
    """Either Obsidian answers with the documented JSON, or it is not usable.

    Both outcomes are acceptable — the app may simply not be running. What would
    NOT be acceptable is the probe raising, or reporting success on output it did
    not understand, and that is what this asserts.
    """
    if shutil.which("obsidian") is None:
        pytest.skip("the obsidian CLI is not installed on this machine")

    from studyloop.second_brain.obsidian_cli import resolve_cli_mode
    from studyloop.settings import SecondBrainConfig

    mode = resolve_cli_mode(SecondBrainConfig(provider="obsidian", use_cli="on"))
    assert mode in {"cli", "files"}


def test_a_probe_against_a_vault_name_that_cannot_exist_reports_files() -> None:
    """The vault-name check is what stops a write landing in the wrong vault."""
    if shutil.which("obsidian") is None:
        pytest.skip("the obsidian CLI is not installed on this machine")

    from studyloop.second_brain.obsidian_cli import resolve_cli_mode
    from studyloop.settings import SecondBrainConfig

    config = SecondBrainConfig(
        provider="obsidian",
        use_cli="on",
        vault_name="studyloop-vault-that-does-not-exist",
    )
    assert resolve_cli_mode(config) == "files"
