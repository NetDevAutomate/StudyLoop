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
# One body, one hub, several views of it. The skill is installed ONCE into
# ~/.agents/skills/ and each harness's own skills directory is a symlink to that
# hub, so an edit lands everywhere at once and a rule that must not vary cannot.
#
# ~/.agents/skills is not a StudyLoop invention: Codex reads it as its USER scope
# and OpenCode lists it as a global search path, which is why the hub is there
# rather than under ~/.studyloop -- Codex is served by the hub with no link at all.

#: The skill directory in the repository. ``SKILL.md`` is the procedure;
#: ``references/harnesses.md`` records what genuinely differs per harness.
_XTILES_SKILL_DIR = "agents/skills/studyloop-xtiles-wind-down"
_XTILES_BODY = f"{_XTILES_SKILL_DIR}/SKILL.md"
_XTILES_REFERENCES = f"{_XTILES_SKILL_DIR}/references/harnesses.md"

#: Harnesses whose skills directory is DOCUMENTED, and therefore linked.
#: pi is absent deliberately: no pi skills directory is documented anywhere, so it
#: gets a self-gated paragraph rather than a link to a guessed path.
#: opencode moved to the hub-served set (2026-09-04 review, Q2): the hub is on its
#: global search path, so a per-harness link was redundant at best.
_XTILES_LINKED_HARNESSES = ("kiro", "claude")

#: Codex, OpenCode and pi need no link of their own -- all discover the hub as
#: a user/global skills directory.
_XTILES_HUB_SERVED_HARNESSES = ("codex", "opencode", "pi")

#: Harnesses whose definition file carries a self-gated paragraph as well.
_XTILES_PARAGRAPH_FILES = (
    "agents/codex/AGENTS.md",
    "agents/pi/AGENTS.md",
    "agents/opencode/study-mentor.md",
)

#: Paragraphs name the installed skill, which every harness reaches through the hub.
_XTILES_POINTER = "studyloop-xtiles-wind-down"

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
    """Every manifest top-level directory is a harness the doctor knows, or shared.

    ``skills/`` joins ``shared/`` on the exemption list: it is the cross-harness
    skills hub, installed once into ``~/.agents/skills`` and symlinked into each
    harness from there, so it is no more a harness name than ``shared`` is. The
    exemptions are enumerated rather than pattern-matched so that a genuinely
    misspelled harness directory still fails here.
    """
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    manifest_tools = {key.split("/", maxsplit=1)[0] for key in manifest["agents"]}
    shared_or_non_detectable = {"shared", "skills"}

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


def test_the_skill_is_one_body_with_per_harness_notes_beside_it() -> None:
    """One procedure, and the harness differences recorded where they belong.

    The offer rule is safety-relevant -- offer once, only behind both gates,
    otherwise say nothing -- and five separately maintained copies of a rule like
    that drift four ways. So SKILL.md is the only place the procedure is written,
    and what genuinely varies per harness (install path, invocation, frontmatter)
    lives in references/harnesses.md next to it.
    """
    repo_root = _repo_root()

    body = repo_root / _XTILES_BODY
    assert body.is_file(), f"{_XTILES_BODY} is missing"
    text = body.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "the skill needs frontmatter"
    assert "name: studyloop-xtiles-wind-down" in text
    for gate in _XTILES_GATES:
        assert gate in text, f"the skill does not state its gate: {gate!r}"

    references = repo_root / _XTILES_REFERENCES
    assert references.is_file(), f"{_XTILES_REFERENCES} is missing"
    notes = references.read_text(encoding="utf-8")
    for tool in (*_XTILES_LINKED_HARNESSES, *_XTILES_HUB_SERVED_HARNESSES, "pi"):
        assert tool in notes.lower(), f"the per-harness notes do not mention {tool}"


def test_the_skill_name_matches_its_directory() -> None:
    """An OpenCode rule, and a good one: a mismatch makes the skill undiscoverable.

    Enforced here rather than trusted, because the failure is silent -- OpenCode
    simply does not list the skill, and nothing says why.
    """
    repo_root = _repo_root()
    directory = Path(_XTILES_SKILL_DIR).name
    text = (repo_root / _XTILES_BODY).read_text(encoding="utf-8")
    assert f"name: {directory}" in text
    assert directory == installers.XTILES_SKILL_NAME


def test_every_release_harness_can_reach_the_skill() -> None:
    """No supported harness is left out, by a link or by the hub or by a paragraph.

    Written as a partition over RELEASE_HARNESSES so that ADDING a harness fails
    this test until someone decides how it reaches the skill. A test enumerating
    only the harnesses that already work would stay green through the omission.
    """
    from studyloop.harnesses import RELEASE_HARNESSES

    release: set[str] = set(RELEASE_HARNESSES)
    covered: set[str] = {
        *_XTILES_LINKED_HARNESSES,
        *_XTILES_HUB_SERVED_HARNESSES,
    }
    assert covered == release, (
        "every release harness must reach the xTiles skill somehow: "
        f"missing {sorted(release - covered)}, "
        f"unknown {sorted(covered - release)}"
    )
    assert set(installers.XTILES_SKILL_LINKS) == set(_XTILES_LINKED_HARNESSES)


def test_harness_links_point_at_the_hub_not_the_repository() -> None:
    """The chain is repo -> hub -> harness, and that is the whole point.

    A harness link straight back into the repository would work, but it would give
    Codex a second path to the same skill and make "where is this installed from"
    have five answers instead of one.
    """
    hub = str(installers.XTILES_SKILL_HUB)
    for tool, spec in installers.XTILES_SKILL_LINKS.items():
        assert spec.source == hub, f"{tool} links to {spec.source}, not the hub"
        assert spec.target.endswith(installers.XTILES_SKILL_NAME)

    shared_targets = {spec.target for spec in installers._SHARED_LINKS}
    assert hub in shared_targets, "the shared pass does not install the hub"


def test_xtiles_paragraph_harnesses_name_the_skill_and_its_gate() -> None:
    """Codex, pi and OpenCode also carry a steering pointer.

    All three discover the hub directly; the paragraph is belt-and-braces and
    states the provider gate without copying the procedure.
    """
    repo_root = _repo_root()
    for rel_path in _XTILES_PARAGRAPH_FILES:
        text = (repo_root / rel_path).read_text(encoding="utf-8")
        assert _XTILES_POINTER in text, f"{rel_path} does not name the skill"
        assert "provider: xtiles" in text, f"{rel_path} states no provider gate"


def test_xtiles_agent_files_are_tracked_in_the_manifest() -> None:
    """Untracked means undetected drift: ``doctor`` compares against the manifest.

    Both the procedure and the per-harness notes are installed files, so an edit to
    either has to show up as a changed hash rather than as a mentor quietly
    following an older instruction than the one in the repository.
    """
    repo_root = _repo_root()
    manifest = json.loads((repo_root / "agents/manifest.json").read_text(encoding="utf-8"))
    expected = {_XTILES_BODY, _XTILES_REFERENCES}
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
    """``studyloop install agents`` reaches every harness it detects, via the hub.

    The owner's decision (F18): the learner does not hand-copy a skill file into one
    harness. Whatever they study in, the wind-down behaves the same -- which is only
    true if the installer, not a README, does the work.

    Installed into a sandbox HOME, because the alternative is a test that edits the
    developer's own agent configuration.
    """
    repo_root = _repo_root()
    detected = sorted(_XTILES_LINKED_HARNESSES)

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
    # Both ends of the harness links move into the sandbox: the SOURCE is the hub,
    # which now lives under the sandbox HOME too.
    monkeypatch.setattr(
        installers,
        "XTILES_SKILL_LINKS",
        {
            tool: installers.LinkSpec(
                _rebase(spec.source, tmp_path), _rebase(spec.target, tmp_path)
            )
            for tool, spec in installers.XTILES_SKILL_LINKS.items()
        },
    )
    monkeypatch.setattr(
        installers,
        "SESSION_MEMORY_SKILL_LINKS",
        {
            tool: installers.LinkSpec(
                _rebase(spec.source, tmp_path), _rebase(spec.target, tmp_path)
            )
            for tool, spec in installers.SESSION_MEMORY_SKILL_LINKS.items()
        },
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

    # The hub arrives once. Codex reads this path natively, so this single link is
    # also Codex's entire installation.
    hub = tmp_path / ".agents/skills/studyloop-xtiles-wind-down"
    assert (hub / "SKILL.md").is_file(), "the skills hub was not installed"
    assert (hub / "references" / "harnesses.md").is_file()

    installed = {
        "kiro": tmp_path / ".kiro/skills/studyloop-xtiles-wind-down",
        "claude": tmp_path / ".claude/skills/studyloop-xtiles-wind-down",
    }
    missing = sorted(tool for tool, path in installed.items() if not (path / "SKILL.md").is_file())
    assert missing == [], f"no skill installed for: {missing}"

    # OpenCode gets NO per-harness link (2026-09-04 review, Q2): the hub itself
    # is on its global search path, and a second link would risk a duplicate
    # listing that nothing has verified OpenCode de-duplicates.
    assert not (tmp_path / ".config/opencode/skills/studyloop-xtiles-wind-down").exists()

    # Every harness reads the SAME bytes. Asserted through the link, not by
    # comparing content: two copies that happen to match today are still two copies.
    for tool, path in installed.items():
        assert path.is_symlink(), f"{tool}'s skill is a copy, not a link"
        assert path.resolve() == hub.resolve(), f"{tool} does not resolve to the hub"

    # And `--uninstall` takes them away again: an opt-in feature that cannot be
    # opted out of is not opt-in.
    installers.install_agent_definitions(repo_root, uninstall=True)
    remaining = sorted(tool for tool, path in installed.items() if path.exists())
    assert remaining == [], f"still installed after uninstall: {remaining}"
    assert not hub.exists(), "the hub survived uninstall"


# ---------------------------------------------------------------------------
# Session memory: every release harness gets one query skill + one real hook
# ---------------------------------------------------------------------------


def test_session_memory_skill_is_canonical_and_reaches_every_release_harness() -> None:
    from studyloop.harnesses import RELEASE_HARNESSES

    repo_root = _repo_root()
    skill = repo_root / "agents/skills/studyloop-session-memory/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "name: studyloop-session-memory" in text
    assert "session_search" in text
    assert "session-query search" in text
    assert "session-export --kiro-only" in text

    # Kiro/Claude need native-directory links. Codex/OpenCode/pi all discover
    # ~/.agents/skills directly, so the hub serves them without duplicate links.
    linked = set(installers.SESSION_MEMORY_SKILL_LINKS)
    hub_served = {"codex", "opencode", "pi"}
    assert linked == {"kiro", "claude"}
    assert linked | hub_served == set(RELEASE_HARNESSES)
    assert any(
        spec.source == "agents/skills/studyloop-session-memory"
        and spec.target == str(installers.SESSION_MEMORY_SKILL_HUB)
        for spec in installers._SHARED_LINKS
    )


def test_every_release_harness_has_a_real_session_export_hook_contract() -> None:
    repo_root = _repo_root()

    kiro = json.loads((repo_root / "agents/kiro/study-mentor.json").read_text())
    assert any("session-export --kiro-only" in hook["command"] for hook in kiro["hooks"]["stop"])
    assert "session-db" in kiro["mcpServers"]

    opencode = repo_root / "agents/opencode/plugins/studyloop-session-export.js"
    assert "session.idle" in opencode.read_text()
    assert "session-export --opencode-only" in opencode.read_text()

    pi = repo_root / "agents/pi/extensions/studyloop-session-export.ts"
    assert "session_shutdown" in pi.read_text()
    assert '"--pi-only"' in pi.read_text()

    # Claude and Codex are merge functions because their global JSON files may
    # already contain user hooks; their behavior is covered in
    # test_harness_export.py. This assertion prevents a release harness from
    # appearing without an explicit hook strategy decision.
    strategies = {"kiro", "opencode", "pi", "claude", "codex"}
    from studyloop.harnesses import RELEASE_HARNESSES

    assert strategies == set(RELEASE_HARNESSES)
