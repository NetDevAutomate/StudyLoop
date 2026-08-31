"""Release contract for the coding harnesses StudyLoop presents to users."""

from __future__ import annotations


def test_initial_prerelease_harness_scope_is_explicit() -> None:
    from studyloop.harnesses import (
        CORE_HARNESSES,
        PREVIEW_HARNESSES,
        RELEASE_HARNESSES,
        SESSION_SOURCE_BY_HARNESS,
    )

    assert CORE_HARNESSES == ("kiro", "codex", "claude")
    assert PREVIEW_HARNESSES == ("opencode", "pi")
    assert (*CORE_HARNESSES, *PREVIEW_HARNESSES) == RELEASE_HARNESSES
    assert "gemini" not in RELEASE_HARNESSES
    assert "grok" not in RELEASE_HARNESSES
    assert SESSION_SOURCE_BY_HARNESS == {
        "kiro": "kiro_cli",
        "codex": "codex",
        "claude": "claude_code",
        "opencode": "opencode",
        "pi": "pi",
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


def test_pi_adapter_uses_project_context_and_native_resume(tmp_path) -> None:
    from studyloop.adapters.pi import ADAPTER

    persona = ADAPTER.setup("# StudyLoop mentor", tmp_path)

    assert persona == tmp_path / "AGENTS.md"
    assert persona.read_text(encoding="utf-8") == "# StudyLoop mentor"
    assert ADAPTER.launch_cmd(persona, resume=False).endswith("pi --no-extensions")
    assert ADAPTER.launch_cmd(persona, resume=True).endswith("pi --no-extensions --continue")


def test_pi_adapter_is_a_complete_release_adapter() -> None:
    from studyloop.adapters.pi import ADAPTER

    assert ADAPTER.name == "pi"
    assert ADAPTER.binary == "pi"
    assert callable(ADAPTER.setup)
    assert callable(ADAPTER.launch_cmd)


def test_pi_context_has_no_unmet_mcp_or_side_file_dependency() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "agents/pi/AGENTS.md"
    text = path.read_text(encoding="utf-8")

    assert "session_search" not in text
    assert "./session-db.md" not in text
    assert "studyloop resume" in text
    assert "studyloop struggles" in text
