"""T2 C13/C16: the optional Obsidian CLI adapter, and how it degrades.

The official Obsidian CLI needs the desktop app to be running, and its command
grammar is not versioned. Both facts shape the design under test here: the file
writer is always the fallback, and the adapter is one module so a grammar change
costs one file.

The three modes exist because "use the CLI" has three honest answers, and the
difference between them is entirely about what the learner is told:

* ``on`` — I have it; if it cannot be used, say so once.
* ``auto`` — use it if it happens to be there, and stay quiet if not. A learner
  whose desktop app simply is not running must not see a warning on every
  publish; that is how a warning becomes noise.
* ``off`` — never spawn a subprocess at all.
"""

from __future__ import annotations

import subprocess

import pytest

from studyloop.second_brain.obsidian_cli import (
    DOCUMENTED_COMMANDS,
    PROBE_TIMEOUT_SECONDS,
    create_note,
    daily_append,
    resolve_cli_mode,
)
from studyloop.settings import SecondBrainConfig


def _config(**overrides: object) -> SecondBrainConfig:
    base: dict[str, object] = {"provider": "obsidian", "use_cli": "auto"}
    base.update(overrides)
    return SecondBrainConfig(**base)  # type: ignore[arg-type]


@pytest.fixture()
def cli_present(monkeypatch):
    """Pretend the ``obsidian`` binary is installed, and record every spawn."""
    calls: list[dict] = []

    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.shutil.which",
        lambda name: "/usr/local/bin/obsidian" if name == "obsidian" else None,
    )

    def _run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"vault": "Personal", "files": 42}', stderr=""
        )

    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.subprocess.run", _run)
    return calls


@pytest.fixture()
def cli_absent(monkeypatch):
    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.shutil.which", lambda name: None)

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("a subprocess was spawned with no binary on PATH")

    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.subprocess.run", _explode)


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------


def test_off_mode_never_spawns(monkeypatch) -> None:
    def _explode(*args: object, **kwargs: object):
        raise AssertionError("off mode spawned a subprocess")

    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.subprocess.run", _explode)
    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.shutil.which", lambda name: _explode())
    assert resolve_cli_mode(_config(use_cli="off")) == "files"


def test_auto_mode_uses_cli_when_binary_and_probe_ok(cli_present) -> None:
    assert resolve_cli_mode(_config(use_cli="auto")) == "cli"
    assert len(cli_present) == 1


def test_auto_mode_falls_back_silently_without_binary(cli_absent, caplog) -> None:
    import logging

    with caplog.at_level(logging.DEBUG, logger="studyloop.second_brain.obsidian_cli"):
        assert resolve_cli_mode(_config(use_cli="auto")) == "files"
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_on_mode_without_binary_warns_once(cli_absent, caplog) -> None:
    """``on`` means the learner asked for it, so silence would be wrong."""
    import logging

    from studyloop.second_brain import obsidian_cli

    obsidian_cli.reset_warning_state()
    with caplog.at_level(logging.WARNING, logger="studyloop.second_brain.obsidian_cli"):
        assert resolve_cli_mode(_config(use_cli="on")) == "files"
        assert resolve_cli_mode(_config(use_cli="on")) == "files"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "obsidian" in warnings[0].getMessage().lower()


def test_probe_uses_exact_argv_shell_false_and_timeout(cli_present) -> None:
    """An argv list and ``shell=False``: a vault name is learner-supplied text.

    A shell string would make a vault called ``My Notes; rm -rf ~`` a command
    injection. The timeout matters because the probe runs on a publish path — a
    hung desktop app must not hang the learner's terminal.
    """
    resolve_cli_mode(_config(use_cli="on", vault_name="Personal"))
    call = cli_present[0]
    assert isinstance(call["argv"], list)
    assert call["argv"][0] == "obsidian"
    assert call["argv"][1] == "eval"
    assert call.get("shell", False) is False
    assert call["timeout"] == PROBE_TIMEOUT_SECONDS
    assert call["capture_output"] is True
    assert "vault=Personal" in call["argv"]


def test_probe_rejects_mismatched_vault_name(monkeypatch) -> None:
    """Answering for the wrong vault is worse than not answering.

    Obsidian can have several vaults open; a probe satisfied by whichever one
    happens to be focused would write the learner's study notes into the wrong
    one.
    """
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.shutil.which", lambda name: "/bin/obsidian"
    )
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, stdout='{"vault": "SomethingElse", "files": 1}', stderr=""
        ),
    )
    assert resolve_cli_mode(_config(use_cli="auto", vault_name="Personal")) == "files"


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(subprocess.TimeoutExpired("obsidian", 10), id="timeout"),
        pytest.param(FileNotFoundError("obsidian"), id="vanished-binary"),
        pytest.param(OSError("permission denied"), id="os-error"),
    ],
)
def test_a_failing_probe_falls_back_rather_than_raising(monkeypatch, outcome) -> None:
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.shutil.which", lambda name: "/bin/obsidian"
    )

    def _raise(*args: object, **kwargs: object):
        raise outcome

    monkeypatch.setattr("studyloop.second_brain.obsidian_cli.subprocess.run", _raise)
    assert resolve_cli_mode(_config(use_cli="auto")) == "files"


def test_non_json_probe_output_is_not_trusted(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.shutil.which", lambda name: "/bin/obsidian"
    )
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    assert resolve_cli_mode(_config(use_cli="auto")) == "files"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_uses_exact_argv_and_rendered_content(cli_present) -> None:
    created = create_note(
        _config(use_cli="on", vault_name="Personal", template="Study Plan"),
        "Study/Plans/python-decorators.md",
        "# body\n",
    )
    assert created is True
    argv = cli_present[-1]["argv"]
    assert argv[:2] == ["obsidian", "create"]
    assert "name=Study/Plans/python-decorators.md" in argv
    assert "template=Study Plan" in argv
    assert "content=# body\n" in argv
    assert "vault=Personal" in argv


def test_create_failure_is_reported_not_raised(monkeypatch) -> None:
    """Every CLI failure degrades to the file writer; nothing is ever lost."""
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.shutil.which", lambda name: "/bin/obsidian"
    )
    monkeypatch.setattr(
        "studyloop.second_brain.obsidian_cli.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, stdout="", stderr="nope"),
    )
    assert create_note(_config(use_cli="on"), "Study/Plans/x.md", "# body\n") is False


def test_the_adapter_never_prompts(cli_present) -> None:
    """``stdin`` is closed on every spawn.

    A subprocess that inherits the terminal can block a publish on a prompt the
    learner cannot see coming — and this runs from an agent's wind-down flow,
    where nobody is watching the terminal at all.
    """
    resolve_cli_mode(_config(use_cli="on"))
    create_note(_config(use_cli="on"), "Study/Plans/x.md", "# body\n")
    for call in cli_present:
        assert call["stdin"] is subprocess.DEVNULL


# ---------------------------------------------------------------------------
# C16 — daily_note, double opt-in, once a day
# ---------------------------------------------------------------------------


def test_daily_append_is_off_by_default(cli_present, tmp_path) -> None:
    assert daily_append(_config(use_cli="on"), tmp_path) is False
    assert not any("daily:append" in str(call["argv"]) for call in cli_present)


def test_daily_append_argv_is_isolated(cli_present, tmp_path) -> None:
    """One line, into the daily note, naming only StudyLoop's own note."""
    assert daily_append(_config(use_cli="on", daily_note=True), tmp_path) is True
    argv = cli_present[-1]["argv"]
    assert argv[:2] == ["obsidian", "daily:append"]
    content = next(arg for arg in argv if arg.startswith("content="))
    assert content.count("\n") == 0
    assert "Study/Today" in content


def test_daily_append_once_per_day_stamp(cli_present, tmp_path) -> None:
    """The daily note is a file the learner owns, so appending twice is spam.

    The stamp lives in the state directory, never in the vault: a marker file
    inside the vault would itself be an unowned StudyLoop write into the
    learner's notes.
    """
    config = _config(use_cli="on", daily_note=True)
    assert daily_append(config, tmp_path) is True
    appends = [c for c in cli_present if "daily:append" in str(c["argv"])]
    assert len(appends) == 1

    assert daily_append(config, tmp_path) is False
    appends = [c for c in cli_present if "daily:append" in str(c["argv"])]
    assert len(appends) == 1

    stamps = list(tmp_path.rglob("*"))
    assert stamps, "the once-a-day stamp must be recorded somewhere"
    assert all(tmp_path in stamp.parents or stamp.parent == tmp_path for stamp in stamps)


def test_daily_append_requires_an_effective_cli_mode(cli_absent, tmp_path) -> None:
    assert daily_append(_config(use_cli="auto", daily_note=True), tmp_path) is False


# ---------------------------------------------------------------------------
# The docs quote these exact lines
# ---------------------------------------------------------------------------


def test_documented_commands_are_the_forms_the_adapter_builds() -> None:
    """The guide's fenced ``obsidian ...`` lines are compared against this tuple.

    One constant rather than prose in two places: the CLI grammar is not
    versioned, so a documented command that no longer matches what the code
    builds is a promise the tool cannot keep.
    """
    assert DOCUMENTED_COMMANDS
    assert all(line.startswith("obsidian ") for line in DOCUMENTED_COMMANDS)
    joined = " ".join(DOCUMENTED_COMMANDS)
    for verb in ("eval", "create", "daily:append"):
        assert verb in joined
