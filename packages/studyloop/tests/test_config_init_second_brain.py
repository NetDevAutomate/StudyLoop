"""T4 C6: ``studyloop config init`` offers second-brain publishing, once.

The question is asked only after the learner has already accepted a vault, and it
defaults to No. Both matter: a vault configured for reading notes is not consent
to start writing into it, and a default-Yes would opt people in through a prompt
they skimmed.

Answering No writes NOTHING — not `provider: none`. Absence already means off, and
a config full of explicit defaults is harder to read and invites the belief that
deleting a key changes behaviour.

``studyloop setup`` is a different wizard and gains no question at all; its test
file is untouched, which is asserted by the fact that it still passes.
"""

from __future__ import annotations

import yaml

from studyloop.shared import init_interactive_config


def _answers(*values: str):
    """A stand-in for ``input`` that returns the given answers in order."""
    remaining = list(values)

    def _next(_prompt: str = "") -> str:
        return remaining.pop(0) if remaining else ""

    return _next


def _run(monkeypatch, tmp_path, answers) -> dict:
    """Drive the wizard to completion and return the config it wrote."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setattr("builtins.input", answers)
    written = init_interactive_config(config_path)
    return yaml.safe_load(written.read_text()) or {}


VAULT_ACCEPTED = ("n", "n", "y")  # knowledge domains: no, notebooklm: no, obsidian: yes


def test_q3_followup_no_writes_nothing(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _run(
        monkeypatch,
        tmp_path,
        _answers(*VAULT_ACCEPTED, str(vault), "n"),
    )
    assert "second_brain" not in config
    assert config["obsidian_base"] == str(vault)


def test_q3_followup_default_is_no(monkeypatch, tmp_path) -> None:
    """An empty answer must not opt the learner in."""
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _run(monkeypatch, tmp_path, _answers(*VAULT_ACCEPTED, str(vault), ""))
    assert "second_brain" not in config


def test_q3_followup_yes_writes_obsidian(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _run(monkeypatch, tmp_path, _answers(*VAULT_ACCEPTED, str(vault), "y"))
    assert config["second_brain"] == {
        "provider": "obsidian",
        "vault_path": str(vault),
    }


def test_the_followup_is_not_asked_when_no_vault_was_given(monkeypatch, tmp_path) -> None:
    """No vault means no folder to write into, so the question is meaningless."""
    prompts: list[str] = []

    def _record(prompt: str = "") -> str:
        prompts.append(prompt)
        return {0: "n", 1: "n", 2: "n"}.get(len(prompts) - 1, "")

    config = _run(monkeypatch, tmp_path, _record)
    assert "second_brain" not in config
    assert not any("publish" in prompt.lower() for prompt in prompts)


def test_what_is_written_loads_back_cleanly(monkeypatch, tmp_path) -> None:
    """The wizard must not be able to produce a config the loader rejects."""
    from studyloop.settings import load_settings

    vault = tmp_path / "vault"
    vault.mkdir()
    _run(monkeypatch, tmp_path, _answers(*VAULT_ACCEPTED, str(vault), "y"))
    settings = load_settings()
    assert settings.second_brain.provider == "obsidian"
    assert settings.second_brain.vault_path == vault


def test_an_existing_second_brain_section_survives_a_rerun(monkeypatch, tmp_path) -> None:
    """Re-running the wizard must not silently reset choices made by hand."""
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "second_brain": {
                    "provider": "obsidian",
                    "vault_path": str(vault),
                    "daily_note": True,
                }
            }
        )
    )
    config = _run(monkeypatch, tmp_path, _answers(*VAULT_ACCEPTED, str(vault), "n"))
    assert config["second_brain"]["daily_note"] is True
