"""Multiplexer seam: herdr is the target, tmux only a migration fallback.

Every test injects a fake ``which`` and a fake runner — no real herdr or tmux
process is ever started.
"""

from __future__ import annotations

import subprocess

import pytest

from studyloop.planning.multiplexer import (
    HerdrBackend,
    Multiplexer,
    TmuxBackend,
    available_backends,
    preferred_backend,
)


def _which(*present: str):
    """Build a fake shutil.which that only knows about ``present``."""
    installed = set(present)

    def _fake(name: str) -> str | None:
        return f"/usr/local/bin/{name}" if name in installed else None

    return _fake


def _runner(stdout: str = "", returncode: int = 0):
    def _fake(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, returncode, stdout, "")

    return _fake


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_herdr_is_preferred_over_tmux() -> None:
    assert preferred_backend(_which("herdr", "tmux")) == "herdr"
    assert available_backends(_which("herdr", "tmux")) == ["herdr", "tmux"]


def test_tmux_is_used_only_when_herdr_is_absent() -> None:
    assert preferred_backend(_which("tmux")) == "tmux"


def test_no_multiplexer_reports_empty() -> None:
    assert preferred_backend(_which()) == ""
    assert available_backends(_which()) == []


def test_detect_builds_the_preferred_backend() -> None:
    assert Multiplexer.detect(which=_which("herdr", "tmux")).name == "herdr"
    assert Multiplexer.detect(which=_which("tmux")).name == "tmux"


def test_detect_falls_back_to_herdr_commands_when_nothing_is_installed() -> None:
    """Better a coherent 'herdr missing' error than a surprise tmux call."""
    assert Multiplexer.detect(which=_which()).name == "herdr"


# ---------------------------------------------------------------------------
# herdr argv construction
# ---------------------------------------------------------------------------


def test_herdr_session_argv() -> None:
    backend = HerdrBackend()
    assert backend.new_session_argv("studyloop-plan-x") == [
        "herdr",
        "--session",
        "studyloop-plan-x",
    ]
    assert backend.new_session_argv("s", "/tmp/wd")[-2:] == ["--cwd", "/tmp/wd"]
    assert backend.attach_argv("s") == ["herdr", "session", "attach", "s"]
    assert backend.session_list_argv() == ["herdr", "session", "list", "--json"]


@pytest.mark.parametrize("direction", ["right", "down"])
def test_herdr_split_argv(direction: str) -> None:
    argv = HerdrBackend().split_argv("s", direction=direction, ratio=0.3)
    assert argv[:3] == ["herdr", "pane", "split"]
    assert "--direction" in argv and direction in argv
    assert "0.3" in argv


def test_herdr_split_rejects_an_unsupported_direction() -> None:
    with pytest.raises(ValueError, match="right\\|down"):
        HerdrBackend().split_argv("s", direction="left", ratio=0.5)


def test_herdr_run_and_send_text_argv() -> None:
    backend = HerdrBackend()
    assert backend.run_argv("p1", ["studyloop", "sidebar"]) == [
        "herdr",
        "pane",
        "run",
        "p1",
        "studyloop",
        "sidebar",
    ]
    assert backend.send_text_argv("p1", "hello") == [
        "herdr",
        "pane",
        "send-text",
        "p1",
        "hello",
    ]


def test_herdr_agent_prompt_argv() -> None:
    assert HerdrBackend().agent_prompt_argv("a1", "why?") == [
        "herdr",
        "agent",
        "prompt",
        "a1",
        "why?",
    ]


def test_tmux_argv_still_maps_for_migration() -> None:
    backend = TmuxBackend()
    assert backend.new_session_argv("s") == ["tmux", "new-session", "-d", "-s", "s"]
    assert backend.split_argv("s", direction="right", ratio=0.3)[2] == "-h"
    assert backend.split_argv("s", direction="down", ratio=0.5)[2] == "-v"


# ---------------------------------------------------------------------------
# Session listing
# ---------------------------------------------------------------------------


def test_session_names_parses_herdr_json() -> None:
    payload = '{"sessions": [{"name": "default"}, {"name": "studyloop-plan-x"}]}'
    mux = Multiplexer(backend=HerdrBackend(), run=_runner(payload))
    assert mux.session_names() == ["default", "studyloop-plan-x"]


def test_session_names_parses_a_bare_json_array() -> None:
    mux = Multiplexer(backend=HerdrBackend(), run=_runner('[{"name": "one"}]'))
    assert mux.session_names() == ["one"]


def test_session_names_parses_tabular_output_and_skips_the_header() -> None:
    table = (
        "name                 status   directory\n"
        "default              running  /tmp\n"
        "plan-x               running  /tmp\n"
    )
    mux = Multiplexer(backend=HerdrBackend(), run=_runner(table))
    assert mux.session_names() == ["default", "plan-x"]


def test_session_names_is_empty_on_failure() -> None:
    assert Multiplexer(run=_runner("boom", returncode=1)).session_names() == []
    assert Multiplexer(run=_runner("")).session_names() == []


def test_session_names_survives_a_raising_runner() -> None:
    def _explode(argv: list[str]) -> subprocess.CompletedProcess:
        msg = "herdr not found"
        raise FileNotFoundError(msg)

    assert Multiplexer(run=_explode).session_names() == []


def test_session_names_survives_malformed_json() -> None:
    assert Multiplexer(run=_runner("{not json")).session_names() == []


def test_session_exists_and_ensure_session_are_idempotent() -> None:
    calls: list[list[str]] = []

    def _record(argv: list[str]) -> subprocess.CompletedProcess:
        calls.append(argv)
        if argv[1:3] == ["session", "list"]:
            return subprocess.CompletedProcess(argv, 0, '{"sessions": [{"name": "here"}]}', "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    mux = Multiplexer(backend=HerdrBackend(), run=_record)
    assert mux.session_exists("here") is True
    # Already present: ensure_session must not try to create it again.
    assert mux.ensure_session("here") is True
    assert not any("--session" in argv for argv in calls)


def test_ensure_session_creates_a_missing_session() -> None:
    created: list[list[str]] = []

    def _record(argv: list[str]) -> subprocess.CompletedProcess:
        if argv[1:3] == ["session", "list"]:
            return subprocess.CompletedProcess(argv, 0, '{"sessions": []}', "")
        created.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    mux = Multiplexer(backend=HerdrBackend(), run=_record)
    assert mux.ensure_session("new-one", cwd="/tmp") is True
    assert created == [["herdr", "--session", "new-one", "--cwd", "/tmp"]]


def test_attach_command_is_returned_not_executed() -> None:
    calls: list[list[str]] = []

    def _record(argv: list[str]) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    mux = Multiplexer(backend=HerdrBackend(), run=_record)
    assert mux.attach_command("plan-x") == ["herdr", "session", "attach", "plan-x"]
    assert calls == [], "attach_command must not run anything"
