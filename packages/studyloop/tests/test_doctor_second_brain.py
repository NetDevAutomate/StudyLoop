"""T4 C7: ``studyloop doctor`` reports a second brain only when there is one.

The registration rule is the point. A learner who has never configured a second
brain must not see rows about software they do not use — the setup wizard does not
ask about it, so reporting on it would be reporting on nothing. That is the same
reasoning the existing Obsidian-export checks are registered conditionally for.

Nothing here can ever ``fail``. A vault on an unmounted drive is worth a warning,
but it is not a broken installation, and a blocking failure would make ``doctor``
useless as a health check for everything else.
"""

from __future__ import annotations

import pytest
import yaml

from studyloop.doctor.config import check_second_brain


@pytest.fixture()
def config(tmp_path, monkeypatch):
    def _write(mapping: dict):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(mapping, default_flow_style=False, sort_keys=False))
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
        return path

    return _write


def _rows(results):
    return {result.name: result for result in results}


def test_no_rows_when_the_section_is_absent(config) -> None:
    config({"topics": []})
    assert check_second_brain() == []


def test_no_rows_when_the_provider_is_none(config) -> None:
    """Explicitly off is still off. Rows would be noise."""
    config({"second_brain": {"provider": "none"}})
    assert check_second_brain() == []


def test_rows_obsidian_ok(config, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config(
        {
            "second_brain": {
                "provider": "obsidian",
                "vault_path": str(vault),
            }
        }
    )
    rows = _rows(check_second_brain())
    assert rows["second_brain_provider"].status == "info"
    assert rows["second_brain_vault"].status == "pass"
    assert rows["second_brain_folder"].status == "info"
    assert all(row.category == "config" for row in rows.values())


def test_no_row_mentions_the_withdrawn_cli_adapter(config, tmp_path) -> None:
    """The adapter was cut before release; doctor must not report on it.

    A row about a feature that does not exist is worse than no row: it tells the
    learner to go looking for a setting they cannot find.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    config({"second_brain": {"provider": "obsidian", "vault_path": str(vault)}})
    rows = check_second_brain()
    assert not any("cli" in row.name for row in rows)
    assert not any("obsidian CLI" in row.message for row in rows)


def test_rows_vault_missing_warns(config, tmp_path) -> None:
    config({"second_brain": {"provider": "obsidian", "vault_path": str(tmp_path / "gone")}})
    rows = _rows(check_second_brain())
    assert rows["second_brain_vault"].status == "warn"
    assert "gone" in rows["second_brain_vault"].message


def test_no_row_is_ever_a_failure(config, tmp_path) -> None:
    """A missing vault is a warning, never a blocking failure."""
    config({"second_brain": {"provider": "obsidian", "vault_path": str(tmp_path / "gone")}})
    assert all(row.status != "fail" for row in check_second_brain())


def test_rows_xtiles_info(config) -> None:
    """One row, pointing at the guide: there is nothing else to check."""
    config({"second_brain": {"provider": "xtiles"}})
    rows = check_second_brain()
    assert len(rows) == 1
    assert rows[0].status == "info"
    assert "second-brain" in rows[0].fix_hint or "second-brain" in rows[0].message


def test_a_broken_section_does_not_crash_the_doctor(config) -> None:
    """``doctor`` is what a learner runs when something is wrong.

    A ConfigError escaping here would take down every other check with it, which
    is the opposite of what a diagnostic tool is for.
    """
    config({"second_brain": {"provider": "obsidan"}})
    rows = check_second_brain()
    assert len(rows) == 1
    assert rows[0].status == "warn"
    assert "second_brain" in rows[0].message


def test_registered_only_when_the_section_exists(config, tmp_path, monkeypatch) -> None:
    """The check reaches the registry only for a learner who opted in."""
    from studyloop.cli._doctor import _get_registry

    config({"topics": []})
    registered = {fn.__name__ for _category, fn in _get_registry()._checkers}
    assert "check_second_brain" not in registered

    vault = tmp_path / "vault"
    vault.mkdir()
    config({"second_brain": {"provider": "obsidian", "vault_path": str(vault)}})
    registered = {fn.__name__ for _category, fn in _get_registry()._checkers}
    assert "check_second_brain" in registered
