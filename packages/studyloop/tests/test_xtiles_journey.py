"""The xTiles setup journey, in the order a learner actually performs it.

Every step here is already covered somewhere: the factory tests prove a stage-one
backend reports itself unavailable, `test_second_brain_cli_core` pins the status
JSON, `test_cli_brain` proves `publish` exits 0, and `test_doctor_second_brain`
proves the info row. What none of them covers is the SEQUENCE — and the sequence
is where this feature can fail in a way no single step reveals:

* `brain enable xtiles` has to leave a config that `brain status` then reads back
  as xTiles. Two tests passing on hand-written config prove nothing about the
  command that writes it.
* `brain publish` has to be a quiet no-op AFTER enabling, not just when handed a
  synthetic settings object.
* `doctor` has to notice the provider the enable command chose, through its own
  opt-in registration path.
* And across the whole journey StudyLoop must write **nothing** except the config
  file. A stage-one provider that quietly created a `Study/` folder, a state file
  or a cache would be a feature nobody asked for, arriving without a code path
  anyone reviewed.

The last one is the reason this file exists as a journey rather than four more
unit tests: "nothing else appeared anywhere" is only checkable across the whole
run.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from studyloop.cli._brain import brain_group


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An isolated HOME, config and plans directory for the whole journey.

    HOME is redirected too: the point of the final assertion is that nothing
    appeared anywhere, and "anywhere" has to include the places a well-meaning
    default would put a cache.
    """
    house = tmp_path / "home"
    house.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump({"topics": []}), encoding="utf-8")
    plans = tmp_path / "plans"
    plans.mkdir()

    monkeypatch.setenv("HOME", str(house))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(plans))
    return tmp_path


def _run(*args: str):
    return CliRunner().invoke(brain_group, list(args))


def _tree(root) -> dict[str, bytes]:
    """Every file under ``root``, by relative path, with its contents."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_xtiles_setup_journey_in_order(home) -> None:
    before = _tree(home)

    # 1. Nothing configured yet. A learner who has not chosen a provider must
    #    not be told about one.
    status = _run("status", "--json")
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["provider"] == "none"

    # 2. Choose xTiles. No vault, no path, no credential -- the whole
    #    configuration for this provider is its name.
    enable = _run("enable", "xtiles")
    assert enable.exit_code == 0, enable.output

    # 3. Status reads back what enable wrote, not what a fixture wrote.
    status = _run("status", "--json")
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["provider"] == "xtiles"
    assert payload["configured"] is True
    assert payload["supports_publish"] is False
    assert payload["supports_pull_notes"] is False
    assert payload["vault_path"] is None

    # 4. Publish is a quiet, successful no-op. This is the step a wind-down
    #    routine runs unconditionally at the end of every session, so a non-zero
    #    exit here would be a failure the learner sees nightly and cannot fix.
    publish = _run("publish", "--json")
    assert publish.exit_code == 0, publish.output
    result = json.loads(publish.output)
    assert result["provider"] == "xtiles"
    assert result["operations"][0]["written"] == []
    assert result["operations"][0]["skipped"], "a skip with no reason is not a report"

    # 5. Pulling notes is equally not an error: there is no file to read, and
    #    saying so is not the same as failing.
    pull = _run("pull", "python-decorators", "--json")
    assert pull.exit_code == 0, pull.output
    assert json.loads(pull.output)["found"] is False

    # 6. Across all of that, exactly one file changed: the config.
    after = _tree(home)
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    assert changed == {"config.yaml"}, (
        f"a stage-one provider wrote something other than the config file: {sorted(changed)}"
    )
    assert yaml.safe_load(after["config.yaml"])["second_brain"]["provider"] == "xtiles"


def test_doctor_reports_the_provider_the_enable_command_chose(home) -> None:
    """Doctor's registration is opt-in, keyed off the config it reads itself.

    Checked after a real `brain enable` rather than against hand-written YAML,
    because the bug this guards is the two halves disagreeing about what
    "configured" looks like on disk.
    """
    from studyloop.doctor.config import check_second_brain

    assert check_second_brain() == [], "an unconfigured learner was told about xTiles"

    assert _run("enable", "xtiles").exit_code == 0

    rows = check_second_brain()
    assert rows, "doctor said nothing after xTiles was enabled"
    assert [row for row in rows if row.status == "fail"] == [], (
        "choosing a provider that has no programmatic backend is not a broken install"
    )
    assert any("xTiles" in row.message for row in rows)
    assert any(row.fix_hint for row in rows), "an info row with no next step is a dead end"
