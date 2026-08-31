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
