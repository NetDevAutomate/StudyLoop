"""StudyLoop's own Kiro agent, ``agents/kiro/studyloop.json``.

Web ACP sessions launched ``kiro-cli acp`` with no ``--agent``, so every one
ran under whatever the learner's *default* Kiro agent happened to be. Until
2026-09-26 that was Kiro's built-in default -- its own system prompt, all of
the learner's personal steering and skills, and every MCP server in their
global ``mcp.json`` -- because kiro-cli 2.24.0 reserves the name
``kiro_default`` and ignored the learner's ``~/.kiro/agents/kiro_default.json``.
Renaming that file made the learner's personal agent the default, and so,
silently, the configuration of StudyLoop's mentor. A learner's own agent is
theirs to change; the mentor must not change with it.

So StudyLoop installs a dedicated agent named ``studyloop`` at install time,
names it on every Kiro ACP launch, and ``studyloop doctor`` proves kiro-cli
can load it (owner steer, 2026-09-26). The agent carries no persona: the
persona is ACP's invisible first turn, and a second one here would compete
with it. It contributes only what StudyLoop owns -- its two MCP servers, the
session-export stop hook and the command denylist the persona agents carry.
It pre-approves nothing: the ACP path pre-approved nothing under the built-in
default either (``allowedTools: []``), and owner decision 2 (#34) is that no
grant is widened without a decision.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from studyloop import installers

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFINITION = REPO_ROOT / "agents/kiro/studyloop.json"
MENTOR = REPO_ROOT / "agents/kiro/study-mentor.json"


def _definition() -> dict:
    return json.loads(DEFINITION.read_text(encoding="utf-8"))


def _mentor() -> dict:
    return json.loads(MENTOR.read_text(encoding="utf-8"))


class TestTheDefinition:
    def test_is_named_studyloop(self) -> None:
        assert _definition()["name"] == "studyloop"

    def test_carries_no_persona(self) -> None:
        definition = _definition()
        assert "prompt" not in definition
        assert definition.get("resources", []) == []

    def test_reaches_exactly_the_studyloop_servers(self) -> None:
        definition = _definition()
        mentor = _mentor()
        assert definition["tools"] == ["@builtin", "@studyloop", "@session-db"]
        assert definition["mcpServers"] == {
            name: mentor["mcpServers"][name] for name in ("studyloop", "session-db")
        }
        # Nothing from the learner's global mcp.json rides along.
        assert not definition.get("includeMcpJson")
        assert not definition.get("useLegacyMcpJson")

    def test_pre_approves_nothing(self) -> None:
        assert _definition()["allowedTools"] == []

    def test_carries_the_persona_agents_hook_and_denylist(self) -> None:
        definition = _definition()
        mentor = _mentor()
        assert definition["hooks"] == mentor["hooks"]
        assert definition["toolsSettings"] == mentor["toolsSettings"]


class TestCreatedAtInstallTime:
    def test_the_installer_links_it(self) -> None:
        links = {(spec.source, spec.target) for spec in installers._TOOL_LINKS["kiro"]}
        assert (
            "agents/kiro/studyloop.json",
            str(installers._HOME / ".kiro/agents/studyloop.json"),
        ) in links

    def test_install_places_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / ".kiro/agents/studyloop.json"
        # The real table's own entry, re-targeted into tmp_path: without the
        # entry nothing is linked, so this fails for the reason it names.
        specs = [
            spec
            for spec in installers._TOOL_LINKS["kiro"]
            if spec.source == "agents/kiro/studyloop.json"
        ]
        monkeypatch.setattr(
            installers,
            "_TOOL_LINKS",
            {"kiro": tuple(installers.LinkSpec(spec.source, str(target)) for spec in specs)},
        )
        monkeypatch.setattr(installers, "_SHARED_LINKS", ())
        monkeypatch.setattr(installers, "XTILES_SKILL_LINKS", {})
        monkeypatch.setattr(installers, "SESSION_MEMORY_SKILL_LINKS", {})
        # Only the link step is under test; nothing else may reach a real home.
        monkeypatch.setattr(installers, "install_session_db_mandate", lambda *_a, **_k: {})
        monkeypatch.setattr(installers, "register_mcp_servers", lambda *_a, **_k: {})

        installers.install_agent_definitions(REPO_ROOT, tools=["kiro"])

        assert target.is_symlink()
        assert target.resolve() == DEFINITION.resolve()
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "studyloop"

    def test_the_manifest_tracks_it(self) -> None:
        manifest = json.loads((REPO_ROOT / "agents/manifest.json").read_text(encoding="utf-8"))
        entry = manifest["agents"]["kiro/studyloop.json"]
        assert entry["hash"] == hashlib.sha256(DEFINITION.read_bytes()).hexdigest()[:16]
        regenerator = (REPO_ROOT / "scripts/update-agent-manifest.py").read_text(encoding="utf-8")
        assert '"kiro/studyloop.json"' in regenerator

    def test_the_nightly_install_job_checks_it_landed(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/nightly-install.yml").read_text(encoding="utf-8")
        assert 'test -e "$HOME/.kiro/agents/studyloop.json"' in workflow


class TestTheAcpLaunchNamesIt:
    @staticmethod
    def _argv(agent: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        import studyloop
        from studyloop.session.transports import acp as acp_module
        from studyloop.web.routes.session import _transport

        captured: dict = {}

        class _Capture:
            def __init__(self, *, resolve_binary, build_argv) -> None:
                captured["build_argv"] = build_argv

        monkeypatch.setattr(acp_module, "ACPTransport", _Capture)
        monkeypatch.setattr(studyloop, "test_hatch_env", lambda _name: None)
        config = SimpleNamespace(agent=agent)
        _transport._build_acp_transport(config)()
        return captured["build_argv"](config)

    def test_kiro_runs_the_studyloop_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._argv("kiro", monkeypatch) == ["kiro-cli", "acp", "--agent", "studyloop"]

    def test_grok_launch_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._argv("grok", monkeypatch) == ["grok", "agent", "stdio"]


# Fixtures are kiro-cli 2.24.0's REAL output, captured 2026-09-26 (paths
# redacted), not a guess at it. Three facts the first version of this check
# got wrong, each pinned below:
#   1. `agent list` writes its whole table to STDERR; stdout is empty.
#   2. `agent validate` exits 0 even when the file is invalid -- the verdict is
#      an `Error:` line on stderr, not the exit code.
#   3. `acp --agent <missing>` does not fail: the session silently falls back
#      to the built-in `kiro_default`. So this check is the only thing that
#      notices an uninstalled or unloadable agent.
_RED = "\x1b[38;5;9m"
_GREY = "\x1b[38;5;244m"
_OFF = "\x1b[0m"
_LIST_HEAD = (
    f"{_RED}Error: {_OFF}File URI not found: file:///home/learner/.kiro/agents/prompts/vibe.md\n"
    f"{_GREY}Workspace: {_OFF}~/work/.kiro/agents\n"
    f"{_GREY}Global:    {_OFF}~/.kiro/agents\n"
    "\n"
    "* default-plus                     Global        \n"
    f"  kiro_default                     {_GREY}(Built-in){_OFF}    Default agent\n"
    "  study-mentor                     Global        AuDHD-aware Socratic study mentor\n"
    "                                                  study sources, shared session history\n"
)
_OURS = (
    "  studyloop                        Global        StudyLoop's own agent for web (ACP)\n"
    "                                                  study and planning sessions\n"
)
_LISTING = _LIST_HEAD + _OURS
_SHADOWED = (
    _LIST_HEAD + f"  studyloop                        {_GREY}(Built-in){_OFF}    Default agent\n"
)
# `agent validate` on a wrong-typed file: exit 0, verdict on stderr.
_INVALID = (
    f"{_RED}Error: {_OFF}Json supplied at /home/learner/.kiro/agents/studyloop.json is invalid:"
    ' invalid type: string "not-a-list", expected a sequence at line 1 column 43\n'
)


class TestDoctorProvesItLoads:
    """The validity test runs against StudyLoop's own agent, never the learner's default."""

    @staticmethod
    def _run(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        installed: bool = True,
        kiro: bool = True,
        validate: tuple[int, str] = (0, ""),
        listing: str = _LISTING,
    ) -> tuple[list, list[list[str]]]:
        from studyloop.doctor import agents as doctor_agents

        monkeypatch.setenv("HOME", str(tmp_path))
        agent_file = tmp_path / ".kiro/agents/studyloop.json"
        if installed:
            agent_file.parent.mkdir(parents=True)
            agent_file.write_text('{"name": "studyloop"}\n', encoding="utf-8")

        calls: list[list[str]] = []

        def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
            calls.append(list(argv))
            if argv[1:3] == ["agent", "validate"]:
                assert argv[3:] == ["--path", str(agent_file)]
                code, err = validate
                return subprocess.CompletedProcess(argv, code, "", err)
            if argv[1:3] == ["agent", "list"]:
                # The real kiro-cli: table on stderr, nothing on stdout.
                return subprocess.CompletedProcess(argv, 0, "", listing)
            raise AssertionError(f"unexpected command {argv}")

        monkeypatch.setattr(
            doctor_agents.shutil,
            "which",
            lambda name: "/opt/bin/kiro-cli" if kiro and name == "kiro-cli" else None,
        )
        monkeypatch.setattr(doctor_agents.subprocess, "run", _run)
        return doctor_agents.check_kiro_studyloop_agent(), calls

    def test_passes_when_kiro_validates_and_lists_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, calls = self._run(monkeypatch, tmp_path)
        assert [(r.name, r.status) for r in results] == [("agent_kiro_studyloop_loads", "pass")]
        assert [c[1:3] for c in calls] == [["agent", "validate"], ["agent", "list"]]

    def test_warns_when_kiro_rejects_it_despite_exit_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, calls = self._run(monkeypatch, tmp_path, validate=(0, _INVALID))
        (result,) = results
        assert result.status == "warn"
        assert 'invalid type: string "not-a-list"' in result.message
        assert "\x1b" not in result.message
        assert result.fix_auto is False
        assert [c[1:3] for c in calls] == [["agent", "validate"]]

    def test_warns_when_validate_exits_non_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, _ = self._run(
            monkeypatch,
            tmp_path,
            validate=(1, "error: You are not logged in, please log in with kiro-cli login\n"),
        )
        (result,) = results
        assert result.status == "warn"
        assert "not logged in" in result.message

    def test_warns_when_a_built_in_shadows_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, _ = self._run(monkeypatch, tmp_path, listing=_SHADOWED)
        (result,) = results
        assert result.status == "warn"
        assert "built-in" in result.message
        assert result.fix_auto is False

    def test_warns_when_kiro_does_not_list_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, _ = self._run(monkeypatch, tmp_path, listing=_LIST_HEAD)
        (result,) = results
        assert result.status == "warn"
        assert "does not list" in result.message
        assert "falls back" in result.message

    def test_a_description_line_naming_it_is_not_a_row(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        wrapped = (
            _LIST_HEAD + "                                                  studyloop sessions\n"
        )
        results, _ = self._run(monkeypatch, tmp_path, listing=wrapped)
        (result,) = results
        assert result.status == "warn"

    def test_warns_and_auto_fixes_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        results, calls = self._run(monkeypatch, tmp_path, installed=False)
        (result,) = results
        assert result.status == "warn"
        assert result.fix_auto is True
        assert "studyloop install agents" in result.fix_hint
        assert calls == []

    def test_is_silent_without_kiro(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        results, calls = self._run(monkeypatch, tmp_path, kiro=False)
        assert results == []
        assert calls == []

    def test_is_registered_with_doctor(self) -> None:
        from studyloop.cli._doctor import _get_registry
        from studyloop.doctor.agents import check_kiro_studyloop_agent

        assert ("agents", check_kiro_studyloop_agent) in _get_registry()._checkers
