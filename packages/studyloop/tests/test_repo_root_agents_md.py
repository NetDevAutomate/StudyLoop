"""The repository-root ``AGENTS.md`` is for contributors, and no install touches it.

Council pass 3, ruling D1: the AGENTS.md convention is instructions for agents
working *in this repository*. The root file used to be a symlink to the learner
persona (the since-retired ``agents/codex/AGENTS.md``), and ``studyloop install
agents --tool codex`` / ``--tool grok`` linked it there, so uninstall ``unlink()``-ed a
git-tracked path and every coding agent opened in the checkout was told it was
a Socratic study mentor. The launch path never used the root link: the Codex and
Grok adapters write the persona into the session directory they launch in.

These tests pin the new contract: the root file is a regular contributor file,
no installer link targets the checkout, and an install/uninstall cycle leaves a
committed checkout clean.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import studyloop.installers as installers

#: The learner persona's identity line. A contributor file that carries it is the
#: old symlink, or a copy of it, under another name.
_MENTOR_IDENTITY = "You are a strict Socratic mentor"


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents" / "manifest.json").exists():
        root = root.parent
    assert (root / "agents" / "manifest.json").exists()
    return root


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def _every_link_spec() -> list[installers.LinkSpec]:
    return [
        *installers._SHARED_LINKS,
        *(spec for specs in installers._TOOL_LINKS.values() for spec in specs),
        *installers.XTILES_SKILL_LINKS.values(),
        *installers.SESSION_MEMORY_SKILL_LINKS.values(),
    ]


def test_root_agents_md_is_a_regular_contributor_file() -> None:
    root = _repo_root()
    path = root / "AGENTS.md"

    assert not path.is_symlink(), f"AGENTS.md is still a link to {os.readlink(path)}"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert _MENTOR_IDENTITY not in text
    # The identity line left the contributor file for the mentor definitions,
    # not for nowhere: every installed prose definition still carries it.
    for relative in ("agents/claude/socratic-mentor.md", "agents/pi/AGENTS.md"):
        assert _MENTOR_IDENTITY in (root / relative).read_text(encoding="utf-8"), relative


def test_root_agents_md_points_contributors_at_the_gates_and_the_two_trip_wires() -> None:
    text = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    for pointer in (
        "CONTRIBUTING.md",
        "docs/contributor-",
        "Justfile",
        "uv run",
        "just e2e",
        # The two rules every agent trips on.
        "agents/manifest.json",
        "reviews/",
        # Where the learner persona really lives, and how it reaches a session.
        "agents/shared/personas/",
    ):
        assert pointer in text, f"AGENTS.md does not mention {pointer!r}"


def test_no_install_link_targets_the_checkout() -> None:
    """Tooling never mutates the tracked worktree: every link lands outside it."""
    in_repo = [
        f"{spec.source} -> {spec.target}"
        for spec in _every_link_spec()
        if "{repo_root}" in spec.target
    ]

    assert in_repo == []


def _rebase(value: str, home: Path) -> str:
    real_home = str(Path.home())
    return str(home) + value[len(real_home) :] if value.startswith(real_home) else value


def _rebase_spec(spec: installers.LinkSpec, home: Path) -> installers.LinkSpec:
    return installers.LinkSpec(
        _rebase(spec.source, home), _rebase(spec.target, home), copy=spec.copy
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize("tool", ["codex", "grok"])
def test_install_then_uninstall_leaves_a_committed_checkout_clean(
    tool: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Install and uninstall against a committed copy of the repository.

    The links are what can reach the checkout, so they run for real against a
    sandbox HOME; the hook, mandate and MCP writers only ever touch HOME and
    have their own uninstall contract (``test_uninstall_contract.py``), so they
    are stubbed out here to keep this test about the checkout.
    """
    root = _repo_root()
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    shutil.copytree(root / "agents", repo / "agents", symlinks=True)
    shutil.copy2(root / "AGENTS.md", repo / "AGENTS.md", follow_symlinks=False)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "checkout under test")

    def snapshot() -> bytes | str:
        path = repo / "AGENTS.md"
        if path.is_symlink():
            return "-> " + os.readlink(path)
        return path.read_bytes() if path.exists() else "<missing>"

    before = snapshot()

    monkeypatch.setattr(installers, "_HOME", home)
    monkeypatch.setenv("GROK_HOME", str(home / ".grok"))
    monkeypatch.setattr(
        installers,
        "_TOOL_LINKS",
        {
            name: tuple(_rebase_spec(spec, home) for spec in specs)
            for name, specs in installers._TOOL_LINKS.items()
        },
    )
    monkeypatch.setattr(
        installers, "_SHARED_LINKS", tuple(_rebase_spec(s, home) for s in installers._SHARED_LINKS)
    )
    for table in ("XTILES_SKILL_LINKS", "SESSION_MEMORY_SKILL_LINKS"):
        monkeypatch.setattr(
            installers,
            table,
            {name: _rebase_spec(spec, home) for name, spec in getattr(installers, table).items()},
        )
    monkeypatch.setattr(installers, "install_session_db_mandate", lambda *_a, **_k: {})
    monkeypatch.setattr(installers, "install_codex_session_end_hook", lambda **_k: 0)
    monkeypatch.setattr(installers, "install_grok_session_end_hook", lambda **_k: 0)
    monkeypatch.setattr(installers, "register_mcp_servers", lambda *_a, **_k: {})

    # Sandbox-escape guard: every link this run writes must land under tmp_path.
    escaping = sorted(
        str(target)
        for spec in _every_link_spec()
        if not (target := installers._render_target(spec.target, repo))
        .resolve()
        .is_relative_to(tmp_path.resolve())
    )
    assert escaping == [], f"installer would write outside the sandbox: {escaping}"

    installed = installers.install_agent_definitions(repo, tools=[tool])
    assert installed["shared"] > 0, "positive control: the sandboxed install linked nothing"
    assert snapshot() == before, "install changed the checkout's AGENTS.md"

    installers.install_agent_definitions(repo, tools=[tool], uninstall=True)

    assert snapshot() == before, "uninstall changed the checkout's AGENTS.md"
    assert _git(repo, "status", "--porcelain") == ""
