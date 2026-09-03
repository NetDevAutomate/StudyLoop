"""Contracts that keep installer, doctor, manifest, and docs in sync."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import studyloop.doctor.agents as doctor_agents
import studyloop.installers as installers


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/manifest.json").exists():
        root = root.parent
    assert (root / "agents/manifest.json").exists()
    return root


# ---------------------------------------------------------------------------
# The xTiles wind-down skill (T5 C5)
# ---------------------------------------------------------------------------
#
# One body, five harnesses. The body is the only place the behaviour is
# written down; the two skill wrappers and the three steering paragraphs are
# pointers at it, because a rule copied five times drifts four ways.

#: The single shared body, installed through ``_SHARED_LINKS``.
_XTILES_BODY = "agents/shared/xtiles-wind-down.md"

#: Harnesses with a native skills directory get a thin wrapper directory.
_XTILES_WRAPPER_DIRS = {
    "kiro": "agents/kiro/skills/studyloop-xtiles-wind-down",
    "claude": "agents/claude/skills/studyloop-xtiles-wind-down",
}

#: Harnesses whose definition file carries a self-gated paragraph instead.
_XTILES_PARAGRAPH_FILES = (
    "agents/codex/AGENTS.md",
    "agents/pi/AGENTS.md",
    "agents/opencode/study-mentor.md",
)

#: Every pointer names the installed path, not the repo path: the harness reads
#: it from ``~/.agents/shared``, which is where ``_SHARED_LINKS`` puts it.
_XTILES_POINTER = "~/.agents/shared/xtiles-wind-down.md"

#: The gate. Without both halves the skill would talk about xTiles to learners
#: who have never heard of it, at the end of every session.
_XTILES_GATES = ("studyloop brain status --json", "provider: xtiles", "xtiles")


def _installer_sources_by_tool() -> dict[str, set[str]]:
    return {
        tool: {spec.source for spec in installers._TOOL_LINKS[tool]}
        for tool in installers._AGENT_CHOICES
    }


def _is_installed_source(source: str, installer_sources: set[str]) -> bool:
    return source in installer_sources or any(
        source.startswith(f"{installer_source}/") for installer_source in installer_sources
    )


def _definition_sources_by_tool() -> dict[str, set[str]]:
    definition_names = {"AGENTS.md", "socratic-mentor.md", "study-mentor.json", "study-mentor.md"}
    ignored_names = {"GEMINI.md"}
    result: dict[str, set[str]] = {}
    for tool, sources in _installer_sources_by_tool().items():
        result[tool] = {
            source
            for source in sources
            if Path(source).name in definition_names
            and Path(source).name not in ignored_names
            and "/skills/" not in source
        }
    return result


def test_all_installer_agent_sources_exist() -> None:
    repo_root = _repo_root()
    missing = sorted(
        source
        for sources in _installer_sources_by_tool().values()
        for source in sources
        if not (repo_root / source).exists()
    )

    assert missing == []


def test_manifest_agent_entries_exist_and_match_installer_sources() -> None:
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    manifest_sources = {f"agents/{key}" for key in manifest["agents"]}
    installer_sources = set().union(*_installer_sources_by_tool().values())
    installer_sources.update(spec.source for spec in installers._SHARED_LINKS)

    assert sorted(source for source in manifest_sources if not (repo_root / source).exists()) == []
    assert (
        sorted(
            source
            for source in manifest_sources
            if not _is_installed_source(source, installer_sources)
        )
        == []
    )
    assert {
        key: meta["hash"]
        for key, meta in manifest["agents"].items()
        if hashlib.sha256((repo_root / "agents" / key).read_bytes()).hexdigest()[:16]
        != meta["hash"]
    } == {}


def test_installed_agent_definition_sources_have_manifest_entries() -> None:
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    manifest_keys = set(manifest["agents"])
    expected_keys = {
        source.removeprefix("agents/")
        for sources in _definition_sources_by_tool().values()
        for source in sources
    }

    assert expected_keys <= manifest_keys


def test_tools_with_manifest_entries_are_in_doctor_registry() -> None:
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    manifest_tools = {key.split("/", maxsplit=1)[0] for key in manifest["agents"]}
    shared_or_non_detectable = {"shared"}

    assert sorted(manifest_tools - shared_or_non_detectable - set(doctor_agents.TOOL_AGENTS)) == []


def test_doctor_agent_registry_paths_match_installer_targets() -> None:
    doctor_paths = {tool: path for tool, (_, path) in doctor_agents.TOOL_AGENTS.items()}
    installer_targets = {
        tool: {
            str(Path(spec.target.format(repo_root="{repo_root}")).expanduser())
            for spec in installers._TOOL_LINKS[tool]
        }
        for tool in set(doctor_paths) & set(installers._TOOL_LINKS)
    }

    assert str(Path(doctor_paths["claude"]).expanduser()) in installer_targets["claude"]
    assert str(Path(doctor_paths["pi"]).expanduser()) in installer_targets["pi"]


def test_agent_install_docs_tool_options_match_installer_choices() -> None:
    text = (_repo_root() / "docs/agent-install.md").read_text(encoding="utf-8")
    documented_tools = set(re.findall(r"studyloop install agents --tool ([a-z-]+)", text))

    assert documented_tools == set(installers._AGENT_CHOICES)


# ---------------------------------------------------------------------------
# xTiles wind-down skill: one body, wrappers that point at it, and an install
# that reaches every detected harness (T5 C5)
# ---------------------------------------------------------------------------


def test_xtiles_skill_wrappers_point_at_shared_body() -> None:
    """The wrappers carry frontmatter and a pointer — never a second copy.

    A harness wrapper exists because Kiro and Claude Code both discover skills
    from a directory of their own. It must stay thin: the moment a wrapper
    restates the procedure, one harness starts behaving differently from the
    other four and nobody can tell which is right.
    """
    repo_root = _repo_root()

    body = repo_root / _XTILES_BODY
    assert body.is_file(), f"{_XTILES_BODY} is missing"
    body_text = body.read_text(encoding="utf-8")
    assert body_text.startswith("---\n"), "the shared body needs skill frontmatter"
    assert "name: studyloop-xtiles-wind-down" in body_text
    for gate in _XTILES_GATES:
        assert gate in body_text, f"the body does not state its gate: {gate!r}"

    for tool, wrapper_dir in _XTILES_WRAPPER_DIRS.items():
        skill = repo_root / wrapper_dir / "SKILL.md"
        assert skill.is_file(), f"{tool} wrapper {skill} is missing"
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{tool} wrapper has no frontmatter"
        assert "name: studyloop-xtiles-wind-down" in text
        assert _XTILES_POINTER in text, f"{tool} wrapper does not point at the shared body"
        # Thin: frontmatter, a heading, and the pointer line. A wrapper that has
        # grown a procedure of its own is a second source of truth.
        assert len(text.splitlines()) <= 12, f"{tool} wrapper is not a thin pointer"


def test_xtiles_paragraph_harnesses_point_at_the_shared_body() -> None:
    """Codex, pi and OpenCode read a steering file, not a skills directory.

    They get one self-gated sentence each rather than a copy of the procedure,
    for the same reason the wrappers stay thin.
    """
    repo_root = _repo_root()
    for rel_path in _XTILES_PARAGRAPH_FILES:
        text = (repo_root / rel_path).read_text(encoding="utf-8")
        assert _XTILES_POINTER in text, f"{rel_path} does not point at the shared body"
        assert "provider: xtiles" in text, f"{rel_path} states no provider gate"


def test_xtiles_agent_files_are_tracked_in_the_manifest() -> None:
    """Untracked means undetected drift: ``doctor`` compares against the manifest.

    The body and both wrappers are installed files, so an edit to any of them
    has to show up as a changed hash rather than as a mentor quietly following
    an older instruction than the one in the repository.
    """
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    expected = {_XTILES_BODY, *(f"{d}/SKILL.md" for d in _XTILES_WRAPPER_DIRS.values())}
    tracked = {f"agents/{key}" for key in manifest["agents"]}

    assert sorted(expected - tracked) == []
    assert {
        rel_path: manifest["agents"][rel_path.removeprefix("agents/")]["hash"]
        for rel_path in sorted(expected)
        if hashlib.sha256((repo_root / rel_path).read_bytes()).hexdigest()[:16]
        != manifest["agents"][rel_path.removeprefix("agents/")]["hash"]
    } == {}


def _rebase(target: str, home: Path) -> str:
    """Point an installer target at a sandbox HOME.

    ``_TOOL_LINKS`` is built once at import time from ``Path.home()``, so a test
    that only patches ``installers._HOME`` would still write into the real
    ~/.kiro. Rewriting the prefix keeps the rest of the target — the part this
    test is actually asserting — exactly as shipped.
    """
    real_home = str(Path.home())
    return str(home) + target[len(real_home) :] if target.startswith(real_home) else target


def test_xtiles_skill_installed_for_each_detected_tool(tmp_path: Path, monkeypatch) -> None:
    """``studyloop install agents`` puts the skill in every harness it detects.

    The owner's decision (F18): the learner does not hand-copy a skill file into
    one harness. Whatever they study in, the wind-down behaves the same — which
    is only true if the installer, not a README, does the work.

    Installed into a sandbox HOME because the alternative is a test that edits
    the developer's own agent configuration.
    """
    repo_root = _repo_root()
    detected = sorted(_XTILES_WRAPPER_DIRS)

    monkeypatch.setattr(installers, "_HOME", tmp_path)
    monkeypatch.setattr(
        installers,
        "_TOOL_LINKS",
        {
            tool: tuple(
                installers.LinkSpec(spec.source, _rebase(spec.target, tmp_path)) for spec in specs
            )
            for tool, specs in installers._TOOL_LINKS.items()
        },
    )
    monkeypatch.setattr(
        installers,
        "_SHARED_LINKS",
        tuple(
            installers.LinkSpec(spec.source, _rebase(spec.target, tmp_path))
            for spec in installers._SHARED_LINKS
        ),
    )
    monkeypatch.setattr(
        installers,
        "_HARNESS_EXPORT",
        {
            tool: installers._HarnessExport(
                Path(_rebase(str(spec.steering_path), tmp_path)), spec.export_flag
            )
            for tool, spec in installers._HARNESS_EXPORT.items()
        },
    )
    monkeypatch.setattr(installers, "detect_available_agent_tools", lambda: detected)

    installers.install_agent_definitions(repo_root)

    # The body arrives once, through the shared link every harness reads.
    assert (tmp_path / ".agents/shared/xtiles-wind-down.md").is_file()

    installed = {
        "kiro": tmp_path / ".kiro/skills/studyloop-xtiles-wind-down/SKILL.md",
        "claude": tmp_path / ".claude/skills/studyloop-xtiles-wind-down/SKILL.md",
    }
    assert sorted(tool for tool, path in installed.items() if not path.is_file()) == []

    # And `--uninstall` takes them away again: an opt-in feature that cannot be
    # opted out of is not opt-in.
    installers.install_agent_definitions(repo_root, uninstall=True)
    assert sorted(tool for tool, path in installed.items() if path.exists()) == []
