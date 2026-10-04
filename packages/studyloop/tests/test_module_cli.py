"""CLI tests for the ``studyloop module`` group (module-contract v1, lane C).

The group is exported from ``studyloop.cli._module`` and NOT registered in ``cli/__init__.py``
(lane W registers it at assembly), so every test drives the group object directly with
``click.testing.CliRunner``. ``--help`` text is documentation: the docs-drift test will
resolve fenced ``studyloop module ...`` examples against it once registered.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from studyloop.cli import cli as root_cli
from studyloop.cli._module import module_group
from studyloop.modules.check import check_module
from studyloop.modules.scaffold import scaffold_module
from studyloop.modules.store import load_lockfile

FIXTURES = Path(__file__).parent / "fixtures" / "modules"
VALID = FIXTURES / "valid-scaffold"


def _run(*args: str):
    return CliRunner().invoke(module_group, list(args))


# ---------------------------------------------------------------------------
# the group itself
# ---------------------------------------------------------------------------


def test_group_is_exported_but_not_registered() -> None:
    """W registers the group at assembly; until then the root CLI must not know ``module``."""
    assert module_group.name == "module"
    assert "module" not in root_cli._lazy_subcommands  # type: ignore[attr-defined]
    result = CliRunner().invoke(root_cli, ["module", "--help"])
    assert result.exit_code == 2
    assert "No such command 'module'" in result.output


def test_help_lists_the_lifecycle_commands() -> None:
    result = _run("--help")
    assert result.exit_code == 0, result.output
    for command in ("check", "new", "add", "list", "remove"):
        assert command in result.output


# ---------------------------------------------------------------------------
# module check
# ---------------------------------------------------------------------------


def test_check_exits_0_on_a_conforming_module() -> None:
    result = _run("check", str(VALID))
    assert result.exit_code == 0, result.output
    assert "ok" in result.output


def test_check_exits_1_and_names_the_rule_file_and_line() -> None:
    result = _run("check", str(FIXTURES / "mc002" / "broken"))
    assert result.exit_code == 1
    assert "MC002" in result.output
    assert "module.yaml:2" in result.output


def test_check_json_matches_the_engine_report() -> None:
    broken = FIXTURES / "mc015" / "broken"
    result = _run("check", "--json", str(broken))
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == check_module(broken).to_dict()
    [finding] = payload["findings"]
    assert finding["rule_id"] == "MC015"
    assert finding["path"] == "decks/echo-basics.json"
    assert isinstance(finding["line"], int)


def test_check_json_on_a_conforming_module_is_ok_with_no_findings() -> None:
    result = _run("check", "--json", str(VALID))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"ok": True, "findings": []}


def test_check_exits_2_when_the_path_is_not_a_directory(tmp_path: Path) -> None:
    result = _run("check", str(tmp_path / "missing"))
    assert result.exit_code == 2
    assert "not a directory" in result.output


# ---------------------------------------------------------------------------
# module new
# ---------------------------------------------------------------------------


def test_new_scaffolds_into_dir_and_the_result_passes_check(tmp_path: Path) -> None:
    result = _run("new", "my-drills", "--dir", str(tmp_path))
    assert result.exit_code == 0, result.output
    module = tmp_path / "my-drills"
    assert (module / "module.yaml").is_file()
    assert check_module(module).ok is True
    check = _run("check", str(module))
    assert check.exit_code == 0, check.output


def test_new_defaults_to_the_current_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _run("new", "here-drills")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "here-drills" / "decks").is_dir()


def test_new_refuses_a_bad_id_and_writes_nothing(tmp_path: Path) -> None:
    result = _run("new", "Bad Id", "--dir", str(tmp_path))
    assert result.exit_code == 1
    assert "not a module id" in result.output
    assert list(tmp_path.iterdir()) == []


def test_new_refuses_an_occupied_destination(tmp_path: Path) -> None:
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "keep.txt").write_text("keep", encoding="utf-8")
    result = _run("new", "taken", "--dir", str(tmp_path))
    assert result.exit_code == 1
    assert "not empty" in result.output
    assert (tmp_path / "taken" / "keep.txt").read_text(encoding="utf-8") == "keep"


# ---------------------------------------------------------------------------
# module add / list / remove (store under a per-test STUDYLOOP_CONFIG)
# ---------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a per-test config dir: ModuleStore() resolves it via get_config_dir()."""
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config / "config.yaml"))
    return config


def test_add_installs_and_list_shows_it(config_dir: Path, tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    result = _run("add", str(module))
    assert result.exit_code == 0, result.output
    assert "installed my-drills 0.1.0 (sha256:" in result.output
    lockfile = config_dir / "modules" / "modules.lock.json"
    assert lockfile.is_file()
    [entry] = load_lockfile(config_dir / "modules")
    assert entry.id == "my-drills"
    assert Path(entry.snapshot).is_dir()

    listed = _run("list")
    assert listed.exit_code == 0, listed.output
    assert listed.output.startswith("my-drills")
    assert "0.1.0" in listed.output

    as_json = _run("list", "--json")
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.output) == [entry.to_dict()]


def test_add_json_prints_the_lock_entry(config_dir: Path, tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    result = _run("add", "--json", str(module))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    [entry] = load_lockfile(config_dir / "modules")
    assert payload == entry.to_dict()


def test_add_refuses_an_unconforming_module_and_shows_the_finding(
    config_dir: Path, tmp_path: Path
) -> None:
    good = scaffold_module(tmp_path / "good", "good-drills")
    assert _run("add", str(good)).exit_code == 0
    lockfile = config_dir / "modules" / "modules.lock.json"
    before = lockfile.read_bytes()

    result = _run("add", str(FIXTURES / "mc011" / "broken"))

    assert result.exit_code == 1
    assert "MC011" in result.output
    assert "## Limits" in result.output
    assert "not installed" in result.output
    assert lockfile.read_bytes() == before
    assert [e.id for e in load_lockfile(config_dir / "modules")] == ["good-drills"]


def test_add_rejects_a_missing_path(config_dir: Path, tmp_path: Path) -> None:
    result = _run("add", str(tmp_path / "nope"))
    assert result.exit_code == 2
    assert not (config_dir / "modules").exists()


def test_list_with_nothing_installed(config_dir: Path) -> None:
    result = _run("list")
    assert result.exit_code == 0, result.output
    assert "no modules installed" in result.output
    assert json.loads(_run("list", "--json").output) == []


def test_remove_is_idempotent(config_dir: Path, tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    assert _run("add", str(module)).exit_code == 0
    [entry] = load_lockfile(config_dir / "modules")

    first = _run("remove", "my-drills")
    assert first.exit_code == 0, first.output
    assert "removed my-drills" in first.output
    assert load_lockfile(config_dir / "modules") == []
    assert not Path(entry.snapshot).exists()

    second = _run("remove", "my-drills")
    assert second.exit_code == 0, second.output
    assert "not installed" in second.output


# ---------------------------------------------------------------------------
# C6 -- help text is documentation: every command carries resolvable examples
# ---------------------------------------------------------------------------

_EXAMPLE_RE = re.compile(r"^studyloop module\b.*")


def _commands() -> dict[str, click.Command]:
    ctx = click.Context(module_group, info_name="module")
    return {
        name: cmd
        for name in module_group.list_commands(ctx)
        if (cmd := module_group.get_command(ctx, name))
    }


def _examples(cmd: click.Command) -> list[str]:
    help_text = cmd.help or ""
    if "Examples:" not in help_text:
        return []
    after = help_text.split("Examples:", 1)[1]
    return [line.strip() for line in after.splitlines() if _EXAMPLE_RE.match(line.strip())]


def _declared_options(cmd: click.Command) -> set[str]:
    opts: set[str] = {"--help"}
    for param in cmd.params:
        if isinstance(param, click.Option):
            opts.update(param.opts)
            opts.update(param.secondary_opts)
    return opts


def test_every_command_has_examples_that_resolve_against_the_group() -> None:
    """The docs-drift test will validate ``studyloop module ...`` lines in ``Examples:``
    sections once W registers the group; this is the same contract, applied now."""
    commands = _commands()
    assert set(commands) == {"check", "new", "add", "list", "remove"}
    problems: list[str] = []
    for name, cmd in commands.items():
        examples = _examples(cmd)
        if not examples:
            problems.append(f"{name}: no `studyloop module ...` line under Examples:")
            continue
        for example in examples:
            tokens = shlex.split(example)
            if tokens[:3] != ["studyloop", "module", name]:
                problems.append(
                    f"{name}: example does not start with `studyloop module {name}`: {example}"
                )
                continue
            declared = _declared_options(cmd)
            for token in tokens[3:]:
                if token.startswith("-"):
                    opt = token.split("=", 1)[0]
                    if opt not in declared:
                        problems.append(f"{name}: {opt!r} is not a declared option ({example})")
    assert problems == []


def test_help_states_exit_codes_and_the_no_network_promise() -> None:
    commands = _commands()
    # Click rewraps paragraphs, so compare on whitespace-normalised text.
    check_help = " ".join(_run("check", "--help").output.split())
    assert "Exit 0 when the module conforms" in check_help
    assert "exit 1 on any finding" in check_help
    assert "exit 2 when PATH is not a directory" in check_help
    add_help = " ".join(_run("add", "--help").output.split())
    assert "no fetch" in add_help and "No network access" in add_help
    assert "modules.lock.json" in add_help
    remove_help = " ".join(_run("remove", "--help").output.split())
    assert "Idempotent" in remove_help
    for name, cmd in commands.items():
        result = _run(name, "--help")
        assert result.exit_code == 0, (name, result.output)
        assert (cmd.help or "").strip(), f"{name} has no help text"
