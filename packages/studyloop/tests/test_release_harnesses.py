"""Release contract for the coding harnesses StudyLoop presents to users."""

from __future__ import annotations


def test_initial_prerelease_harness_scope_is_explicit() -> None:
    from studyloop.harnesses import (
        CORE_HARNESSES,
        PREVIEW_HARNESSES,
        RELEASE_HARNESSES,
        SESSION_SOURCE_BY_HARNESS,
    )

    # pi promoted 2026-09-16 (issue #21 evidence receipt); opencode and grok
    # stay preview with the reasons named in that receipt.
    assert CORE_HARNESSES == ("kiro", "codex", "claude", "pi")
    assert PREVIEW_HARNESSES == ("opencode", "grok")
    assert (*CORE_HARNESSES, *PREVIEW_HARNESSES) == RELEASE_HARNESSES
    assert "gemini" not in RELEASE_HARNESSES
    assert "grok" in RELEASE_HARNESSES
    assert SESSION_SOURCE_BY_HARNESS == {
        "kiro": "kiro_cli",
        "codex": "codex",
        "claude": "claude_code",
        "opencode": "opencode",
        "pi": "pi",
        "grok": "grok",
    }


def test_release_scope_drives_installer_doctor_and_web_picker() -> None:
    from studyloop.doctor.agents import TOOL_AGENTS
    from studyloop.harnesses import RELEASE_HARNESSES
    from studyloop.installers import _AGENT_CHOICES
    from studyloop.web.routes.session._options import _agent_options

    assert _AGENT_CHOICES == RELEASE_HARNESSES
    assert tuple(TOOL_AGENTS) == RELEASE_HARNESSES
    assert tuple(option["value"] for option in _agent_options()) == RELEASE_HARNESSES


def test_release_registry_contains_only_supported_builtins() -> None:
    from studyloop.adapters.registry import get_all_adapters, reset_registry
    from studyloop.harnesses import RELEASE_HARNESSES

    reset_registry()
    try:
        assert tuple(get_all_adapters()) == RELEASE_HARNESSES
    finally:
        reset_registry()


def test_pi_adapter_uses_project_context_and_native_resume(tmp_path, monkeypatch) -> None:
    import shlex

    import studyloop.installers as installers
    from studyloop.adapters.pi import ADAPTER

    monkeypatch.setattr(installers, "_HOME", tmp_path / "home")  # no export extension installed
    persona = ADAPTER.setup("# StudyLoop mentor", tmp_path)

    assert persona == tmp_path / "AGENTS.md"
    assert persona.read_text(encoding="utf-8") == "# StudyLoop mentor"
    assert shlex.split(ADAPTER.launch_cmd(persona, False))[1:] == ["--no-extensions"]
    assert shlex.split(ADAPTER.launch_cmd(persona, True))[1:] == ["--no-extensions", "--continue"]


def test_pi_adapter_loads_only_the_installed_export_extension(tmp_path, monkeypatch) -> None:
    """Council pass 3, D3 (V1): ``--no-extensions`` keeps the learner's own pi
    extensions out of a mentor session, and ``-e <path>`` -- which pi documents
    as still working under ``--no-extensions`` -- loads StudyLoop's export
    extension alone, so the session reaches the database without depending on
    the model obeying the mandate. The path is the one the installer writes,
    and a HOME with a space in it still splits back to that exact path."""
    import shlex

    import studyloop.installers as installers
    from studyloop.adapters.pi import ADAPTER

    monkeypatch.setattr(installers, "_HOME", tmp_path / "learner home")
    extension = installers._pi_hook_path()
    extension.parent.mkdir(parents=True)
    extension.write_text("// export extension\n", encoding="utf-8")
    persona = ADAPTER.setup("# StudyLoop mentor", tmp_path)

    fresh = shlex.split(ADAPTER.launch_cmd(persona, False))
    resumed = shlex.split(ADAPTER.launch_cmd(persona, True))

    assert fresh[1:] == ["--no-extensions", "-e", str(extension)]
    assert resumed[1:] == ["--no-extensions", "-e", str(extension), "--continue"]


def test_pi_adapter_is_a_complete_release_adapter() -> None:
    from studyloop.adapters.pi import ADAPTER

    assert ADAPTER.name == "pi"
    assert ADAPTER.binary == "pi"
    assert callable(ADAPTER.setup)
    assert callable(ADAPTER.launch_cmd)


def test_pi_context_has_query_fallback_without_unmet_mcp_dependency() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "agents/pi/AGENTS.md"
    text = path.read_text(encoding="utf-8")

    assert "studyloop-session-memory" in text
    assert "session_search" in text
    assert "session-query search" in text
    assert "when its MCP server is connected" in text
    assert "./session-db.md" not in text
