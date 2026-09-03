"""T4: the whole ``studyloop brain`` group.

The design pressure on this surface is that an agent runs it unattended at
wind-down. So the tests are as much about what the commands DO NOT do — never
prompt, never write on a dry run, never fail because a feature is switched off —
as about what they print.

Every failure that can be fixed by the learner names the fix in its message.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from studyloop.cli._brain import brain_group
from studyloop.planning import Mission, StudyPlan, create_plan
from studyloop.planning.store import plan_path


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


@pytest.fixture()
def config(tmp_path, monkeypatch):
    """Write a config.yaml, and isolate the plans directory."""
    path = tmp_path / "config.yaml"
    plans = tmp_path / "plans"
    plans.mkdir()
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(path))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(plans))

    def _write(mapping: dict):
        path.write_text(yaml.dump(mapping, default_flow_style=False, sort_keys=False))
        return path

    _write({"topics": []})
    return _write


@pytest.fixture()
def obsidian(config, vault):
    """A configured Obsidian provider with the CLI adapter off."""
    config(
        {
            "topics": [],
            "second_brain": {
                "provider": "obsidian",
                "vault_path": str(vault),
                "use_cli": "off",
                "backlinks": False,
            },
        }
    )
    return vault


def _seed(plan_id: str, *, status: str = "active") -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        topics=["python"],
        mission=Mission(why="Because it keeps coming up."),
    )
    create_plan(plan)
    return plan


def _run(*args: str):
    return CliRunner().invoke(brain_group, list(args))


# ---------------------------------------------------------------------------
# C1 — status
# ---------------------------------------------------------------------------


def test_status_human_lines(obsidian) -> None:
    result = _run("status")
    assert result.exit_code == 0
    for field in ("provider", "configured", "available", "folder", "use_cli"):
        assert field in result.output


def test_help_lists_every_command() -> None:
    result = _run("--help")
    assert result.exit_code == 0
    for command in ("status", "publish", "pull", "enable", "template"):
        assert command in result.output


# ---------------------------------------------------------------------------
# C2 — publish
# ---------------------------------------------------------------------------


def test_publish_defaults_today_plus_active(obsidian) -> None:
    """No selector means "the useful thing": today, plus every active plan.

    A wind-down flow should not have to enumerate plans, and a learner asking for
    "publish" almost never means "publish a draft I abandoned".
    """
    _seed("python-decorators", status="active")
    _seed("sql-windows", status="active")
    _seed("abandoned-idea", status="draft")

    result = _run("publish", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    written = {path for op in payload["operations"] for path in op["written"]}
    assert "Study/Today.md" in written
    assert "Study/Plans/python-decorators.md" in written
    assert "Study/Plans/sql-windows.md" in written
    assert "Study/Plans/abandoned-idea.md" not in written


def test_publish_all_includes_every_status(obsidian) -> None:
    _seed("python-decorators", status="active")
    _seed("abandoned-idea", status="draft")
    payload = json.loads(_run("publish", "--all", "--json").output)
    written = {path for op in payload["operations"] for path in op["written"]}
    assert "Study/Plans/abandoned-idea.md" in written


def test_publish_named_plan_only(obsidian) -> None:
    _seed("python-decorators")
    _seed("sql-windows")
    payload = json.loads(_run("publish", "--plan", "python-decorators", "--json").output)
    written = {path for op in payload["operations"] for path in op["written"]}
    assert written == {"Study/Plans/python-decorators.md"}


def test_publish_today_only(obsidian) -> None:
    _seed("python-decorators")
    payload = json.loads(_run("publish", "--today", "--json").output)
    written = {path for op in payload["operations"] for path in op["written"]}
    assert written == {"Study/Today.md"}


def test_publish_dry_run_writes_nothing(obsidian) -> None:
    """A dry run must be safe to point at anything.

    It reports what WOULD be written, so the paths still have to be computed --
    which is exactly where a careless implementation writes them.
    """
    _seed("python-decorators")
    before = sorted(p.name for p in obsidian.rglob("*"))

    result = _run("publish", "--plan", "python-decorators", "--dry-run", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert "Study/Plans/python-decorators.md" in payload["operations"][0]["written"]
    assert sorted(p.name for p in obsidian.rglob("*")) == before


def test_publish_dry_run_leaves_the_plan_untouched(obsidian) -> None:
    _seed("python-decorators")
    before = plan_path("python-decorators").read_bytes()
    _run("publish", "--dry-run")
    assert plan_path("python-decorators").read_bytes() == before


def test_publish_unconfigured_exits_zero_with_a_reason(config) -> None:
    """Off is a state the caller asked about, not an error.

    Exit 1 here would make `studyloop brain publish` unusable in any wind-down
    protocol that runs it unconditionally.
    """
    config({"topics": []})
    result = _run("publish", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["operations"][0]["skipped"] == ["Second brain is not configured."]


def test_publish_missing_vault_exit_1_nothing_written(config, tmp_path) -> None:
    config(
        {
            "topics": [],
            "second_brain": {
                "provider": "obsidian",
                "vault_path": str(tmp_path / "not-mounted"),
                "use_cli": "off",
            },
        }
    )
    _seed("python-decorators")
    result = _run("publish", "--plan", "python-decorators")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "studyloop brain enable obsidian" in result.output
    assert not (tmp_path / "not-mounted").exists()


def test_publish_unknown_plan_is_one_line(obsidian) -> None:
    result = _run("publish", "--plan", "no-such-plan")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "no-such-plan" in result.output


def test_publish_with_no_plans_at_all_still_publishes_today(obsidian) -> None:
    payload = json.loads(_run("publish", "--json").output)
    written = {path for op in payload["operations"] for path in op["written"]}
    assert written == {"Study/Today.md"}


def test_publish_reports_unchanged_on_the_second_run(obsidian) -> None:
    _seed("python-decorators")
    _run("publish", "--plan", "python-decorators")
    result = _run("publish", "--plan", "python-decorators")
    assert result.exit_code == 0
    assert "unchanged" in result.output


# ---------------------------------------------------------------------------
# C3 — pull
# ---------------------------------------------------------------------------


def test_pull_prints_notes(obsidian) -> None:
    _seed("python-decorators")
    sibling = obsidian / "Study" / "Plans" / "python-decorators.notes.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("What I actually think.\n")

    result = _run("pull", "python-decorators")
    assert result.exit_code == 0
    assert "What I actually think." in result.output


def test_pull_missing_is_not_an_error(obsidian) -> None:
    _seed("python-decorators")
    result = _run("pull", "python-decorators", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["found"] is False


def test_pull_writes_nothing(obsidian) -> None:
    _seed("python-decorators")
    before = sorted(p.name for p in obsidian.rglob("*"))
    _run("pull", "python-decorators")
    assert sorted(p.name for p in obsidian.rglob("*")) == before


def test_pull_when_unconfigured_is_not_an_error(config) -> None:
    config({"topics": []})
    result = _run("pull", "python-decorators", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output)["found"] is False


# ---------------------------------------------------------------------------
# C4 — enable
# ---------------------------------------------------------------------------


def test_enable_writes_section_preserving_other_keys(config, vault) -> None:
    """Read-modify-write. A learner's whole config must survive this command."""
    path = config(
        {
            "obsidian_base": "~/Obsidian",
            "topics": [{"name": "Python", "slug": "python"}],
            "web_port": 9999,
        }
    )
    result = _run("enable", "obsidian", "--vault", str(vault))
    assert result.exit_code == 0, result.output

    written = yaml.safe_load(path.read_text())
    assert written["web_port"] == 9999
    assert written["topics"] == [{"name": "Python", "slug": "python"}]
    assert written["obsidian_base"] == "~/Obsidian"
    assert written["second_brain"]["provider"] == "obsidian"
    assert written["second_brain"]["vault_path"] == str(vault)


def test_enable_preserves_existing_second_brain_subkeys(config, vault) -> None:
    """Changing the vault must not silently reset the learner's other choices."""
    path = config(
        {
            "topics": [],
            "second_brain": {
                "provider": "obsidian",
                "vault_path": "/old",
                "daily_note": True,
                "vault_name": "Personal",
            },
        }
    )
    _run("enable", "obsidian", "--vault", str(vault))
    written = yaml.safe_load(path.read_text())["second_brain"]
    assert written["vault_path"] == str(vault)
    assert written["daily_note"] is True
    assert written["vault_name"] == "Personal"


def test_enable_accepts_folder_and_cli_mode(config, vault) -> None:
    path = config({"topics": []})
    _run("enable", "obsidian", "--vault", str(vault), "--folder", "Learning", "--cli", "on")
    written = yaml.safe_load(path.read_text())["second_brain"]
    assert written["folder"] == "Learning"
    assert written["use_cli"] == "on"


def test_enable_refuses_missing_vault_without_create(config, tmp_path) -> None:
    """Pointing at a typo'd path silently would mean nothing ever appears."""
    config({"topics": []})
    result = _run("enable", "obsidian", "--vault", str(tmp_path / "typo"))
    assert result.exit_code == 1
    assert "--create" in result.output
    assert not (tmp_path / "typo").exists()


def test_enable_creates_the_vault_folder_on_request(config, tmp_path) -> None:
    config({"topics": []})
    target = tmp_path / "new-vault"
    result = _run("enable", "obsidian", "--vault", str(target), "--create")
    assert result.exit_code == 0, result.output
    assert target.is_dir()


def test_enable_writes_a_validated_section(config, vault) -> None:
    """What `enable` writes must load back cleanly.

    A command that writes a config the loader then rejects is worse than no
    command: the learner is left with a broken file they did not hand-edit.
    """
    config({"topics": []})
    _run("enable", "obsidian", "--vault", str(vault))
    from studyloop.settings import load_settings

    assert load_settings().second_brain.provider == "obsidian"


def test_enable_xtiles_points_at_docs(config) -> None:
    path = config({"topics": []})
    result = _run("enable", "xtiles")
    assert result.exit_code == 0, result.output
    assert "second-brain" in result.output
    assert yaml.safe_load(path.read_text())["second_brain"]["provider"] == "xtiles"


def test_enable_none_turns_it_off_again(config, vault) -> None:
    path = config(
        {"topics": [], "second_brain": {"provider": "obsidian", "vault_path": str(vault)}}
    )
    result = _run("enable", "none")
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(path.read_text())["second_brain"]["provider"] == "none"


def test_enable_json_reports_what_it_wrote(config, vault) -> None:
    config({"topics": []})
    payload = json.loads(_run("enable", "obsidian", "--vault", str(vault), "--json").output)
    assert payload["second_brain"]["provider"] == "obsidian"
    assert payload["config_path"].endswith("config.yaml")


# ---------------------------------------------------------------------------
# C5 — template
# ---------------------------------------------------------------------------


def test_template_lists_names_by_default(config) -> None:
    result = _run("template")
    assert result.exit_code == 0
    assert "Study Plan.md" in result.output


def test_template_print_exact_bytes(config) -> None:
    from studyloop.second_brain.templates import read_template

    result = _run("template", "--print", "Study Plan.md")
    assert result.exit_code == 0
    assert result.output == read_template("Study Plan.md")


def test_template_print_unknown_name_is_one_line(config) -> None:
    result = _run("template", "--print", "Nope.md")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "Unknown template" in result.output


def test_template_install_creates_only(obsidian) -> None:
    result = _run("template", "--install")
    assert result.exit_code == 0, result.output
    assert (obsidian / "Templates" / "StudyLoop" / "Today.md").is_file()


def test_template_install_refuses_existing(obsidian) -> None:
    existing = obsidian / "Templates" / "StudyLoop" / "Today.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# Mine\n")
    result = _run("template", "--install")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert existing.read_text() == "# Mine\n"


def test_template_install_needs_a_vault(config) -> None:
    """Without a provider there is no vault to install into, and saying so beats
    guessing at the learner's Obsidian folder."""
    config({"topics": []})
    result = _run("template", "--install")
    assert result.exit_code == 1
    assert "vault" in result.output.lower()


def test_template_install_json_lists_paths(obsidian) -> None:
    payload = json.loads(_run("template", "--install", "--json").output)
    assert any(path.endswith("StudyLoop/Today.md") for path in payload["installed"])
