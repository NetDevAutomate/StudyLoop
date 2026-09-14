"""Installed prompt surfaces instruct only commands and tools that exist.

Every test here is a doc-vs-code contract: it derives a SET from real code
(console-script tables, ``installers._MCP_HARNESSES``, adapter ``mcp_setup``)
and compares it against what the prose files under ``agents/`` actually
instruct, rather than pinning line numbers or copied prose.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/manifest.json").exists():
        root = root.parent
    assert (root / "agents/manifest.json").exists()
    return root


def _agents_text_files() -> list[Path]:
    """Every prose/config file under ``agents/`` a mentor could read as instructions.

    Excludes binary-ish or non-instructional assets (images, JS/TS plugin code
    is still text but not a source of shell invocations we care about here, so
    it is fine to include -- the regexes below simply won't match).
    """
    root = _repo_root() / "agents"
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix in {".md", ".json", ".sh", ".ts", ".js"}
    ]


# ---------------------------------------------------------------------------
# (a) Every console-script name invoked in agents/** is a real entry point
# ---------------------------------------------------------------------------

_UV_RUN_BIN_RE = re.compile(r"uv run ([a-z]+(?:-[a-z]+)*)\b(?!-\*)")
_BARE_BIN_RE = re.compile(
    r"^\s*(session-[a-z]+|tutor-[a-z]+|study-speak|studyloop-mcp)\b", re.MULTILINE
)


def _declared_console_scripts(repo_root: Path) -> set[str]:
    scripts: set[str] = set()
    for rel in (
        "packages/studyloop/pyproject.toml",
        "packages/agent-session-tools/pyproject.toml",
    ):
        data = tomllib.loads((repo_root / rel).read_text(encoding="utf-8"))
        scripts |= set(data.get("project", {}).get("scripts", {}).keys())
    return scripts


def test_every_invoked_console_script_is_a_declared_entry_point() -> None:
    repo_root = _repo_root()
    declared = _declared_console_scripts(repo_root)
    invoked: dict[str, list[str]] = {}
    for path in _agents_text_files():
        text = path.read_text(encoding="utf-8")
        for match in _UV_RUN_BIN_RE.finditer(text):
            invoked.setdefault(match.group(1), []).append(str(path.relative_to(repo_root)))
        for match in _BARE_BIN_RE.finditer(text):
            invoked.setdefault(match.group(1), []).append(str(path.relative_to(repo_root)))

    missing = {name: files for name, files in invoked.items() if name not in declared}
    assert not missing, (
        "agents/** instructs commands that are not declared console scripts in "
        f"either pyproject.toml: {missing}"
    )


# ---------------------------------------------------------------------------
# (b) "tutor-progress" appears nowhere under agents/ except as the skill
# directory name (agents/kiro/skills/tutor-progress-tracker/...)
# ---------------------------------------------------------------------------


def test_tutor_progress_survives_only_as_the_skill_directory_name() -> None:
    repo_root = _repo_root()
    violations: list[str] = []
    for path in _agents_text_files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"tutor-progress(?!-tracker)", text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(repo_root)}:{line_no}")
    assert not violations, (
        "tutor-progress never shipped as a console script; only "
        f"'tutor-progress-tracker' (the skill directory) may remain: {violations}"
    )


# ---------------------------------------------------------------------------
# W17/W18 -- every tutor-checkpoint invocation parses against the real Typer
# signature (SKILL positional, --notes optional; no --skill, no subcommand).
# ---------------------------------------------------------------------------

_TUTOR_CHECKPOINT_LINE_RE = re.compile(r"^\s*uv run tutor-checkpoint\s+(\S.*)$", re.MULTILINE)


def _tutor_checkpoint_app() -> typer.Typer:
    from agent_session_tools.tutor_checkpoint import record_checkpoint

    app = typer.Typer()
    app.command()(record_checkpoint)
    return app


def _make_sessions_db(tmp_path: Path) -> Path:
    from agent_session_tools.export_sessions import init_db

    db_path = tmp_path / "sessions.db"
    conn = init_db(str(db_path))
    conn.close()
    return db_path


def _placeholder_args(raw: str) -> list[str]:
    """Tokenise a doc-example invocation, replacing <angle-bracket> placeholders."""
    tokens = shlex.split(raw)
    return [re.sub(r"<[^>]+>", "example-skill", tok) for tok in tokens]


def test_every_tutor_checkpoint_invocation_parses(tmp_path, monkeypatch) -> None:
    repo_root = _repo_root()
    db_path = _make_sessions_db(tmp_path)
    monkeypatch.setenv("STUDYLOOP_DB", str(db_path))

    app = _tutor_checkpoint_app()
    invocations: list[tuple[Path, str]] = []
    for path in _agents_text_files():
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for match in _TUTOR_CHECKPOINT_LINE_RE.finditer(text):
            invocations.append((path, match.group(1).strip("`")))

    assert invocations, "expected at least one tutor-checkpoint invocation in agents/**"

    failures = []
    for path, raw in invocations:
        args = _placeholder_args(raw)
        result = runner.invoke(app, args)
        if result.exit_code != 0:
            failures.append((str(path.relative_to(repo_root)), raw, result.output))
    assert not failures, f"tutor-checkpoint invocations that do not parse: {failures}"


# ---------------------------------------------------------------------------
# W19 -- Claude Code status line renders the persisted energy_label, not the
# numeric 1-10 energy field the case statement can never match.
# ---------------------------------------------------------------------------


def test_status_line_renders_the_persisted_energy_label(tmp_path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")

    repo_root = _repo_root()
    script = repo_root / "agents/claude/study-statusline.sh"
    fake_home = tmp_path / "home"
    (fake_home / ".config/studyloop").mkdir(parents=True)
    state_file = fake_home / ".config/studyloop/session-state.json"
    state_file.write_text(json.dumps({"energy": 5, "energy_label": "medium"}))

    result = subprocess.run(
        [bash, str(script)],
        input=json.dumps({"model": {"display_name": "test"}}) + "\n",
        capture_output=True,
        text=True,
        env={"HOME": str(fake_home), "PATH": "/usr/bin:/bin"},
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Med" in result.stdout, f"expected the medium-energy label, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# W20 -- hedge memory_search / get_concept_context exactly where the server
# behind them is actually unwired for the harness reading the instruction.
# ---------------------------------------------------------------------------

#: Prose harness names as they appear in the generic conditional, mapped to
#: the installers.py tool id they correspond to.
_PROSE_HARNESS_TO_TOOL_ID = {
    "Claude Code": "claude",
    "Kiro CLI": "kiro",
    "Codex": "codex",
}


@pytest.mark.parametrize("relative", ["agents/pi/AGENTS.md", "agents/opencode/study-mentor.md"])
def test_memory_search_is_hedged_with_a_session_query_fallback(relative: str) -> None:
    """pi and OpenCode never get session-db-mcp (installers._MCP_HARNESSES),
    so memory_search must name the CLI fallback near the call, exactly as
    agents/skills/studyloop-session-memory/SKILL.md phrases the pattern
    elsewhere (MCP tool when connected, CLI fallback otherwise).
    """
    import studyloop.installers as installers

    assert "opencode" not in installers._MCP_HARNESSES
    assert "pi" not in installers._MCP_HARNESSES

    text = (_repo_root() / relative).read_text(encoding="utf-8")
    match = re.search(r"memory_search", text)
    assert match, f"{relative} no longer mentions memory_search"
    window = text[match.end() : match.end() + 200]
    assert "session-query" in window, (
        f"{relative} instructs memory_search without hedging it for a harness "
        f"session-db-mcp is not wired into: {window!r}"
    )


def test_pi_has_no_mcp_adapter_and_hedges_get_concept_context_too() -> None:
    """pi's adapter defines no mcp_setup at all, so unlike OpenCode it must
    hedge get_concept_context as well, not just memory_search."""
    from studyloop.adapters.pi import ADAPTER

    assert ADAPTER.mcp_setup is None

    text = (_repo_root() / "agents/pi/AGENTS.md").read_text(encoding="utf-8")
    match = re.search(r"get_concept_context", text)
    assert match, "agents/pi/AGENTS.md no longer mentions get_concept_context"
    window = text[max(0, match.start() - 200) : match.end() + 200]
    assert "mastery graph" in window, (
        f"pi has no studyloop MCP server either; get_concept_context needs the "
        f"studyloop mastery graph CLI fallback nearby: {window!r}"
    )


def test_opencode_get_concept_context_is_wired_and_not_hedged() -> None:
    """OpenCode's adapter DOES register studyloop-mcp (write_mcp_config(fmt=
    "opencode")), so get_concept_context must not be hedged there -- hedging a
    tool that already works would misinform the mentor."""
    from studyloop.adapters.opencode import ADAPTER

    assert ADAPTER.mcp_setup is not None

    text = (_repo_root() / "agents/opencode/study-mentor.md").read_text(encoding="utf-8")
    match = re.search(r"get_concept_context", text)
    assert match, "agents/opencode/study-mentor.md no longer mentions get_concept_context"
    window = text[max(0, match.start() - 80) : match.end() + 80]
    assert "mastery graph" not in window, (
        f"get_concept_context is wired for OpenCode via studyloop-mcp; it should "
        f"not carry a CLI-fallback hedge: {window!r}"
    )


def test_agents_md_is_the_codex_symlink() -> None:
    repo_root = _repo_root()
    root_agents = repo_root / "AGENTS.md"
    codex_agents = repo_root / "agents/codex/AGENTS.md"
    assert root_agents.read_text(encoding="utf-8") == codex_agents.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative", ["agents/codex/AGENTS.md", "agents/shared/session-db-mandate.md"]
)
def test_shared_mcp_conditional_matches_the_installers_mcp_harness_set(relative: str) -> None:
    """The generic conditional in the two SHARED files must name exactly the
    harnesses installers._MCP_HARNESSES registers session-db for -- derived
    from code, not copied prose."""
    import studyloop.installers as installers

    text = (_repo_root() / relative).read_text(encoding="utf-8")
    match = re.search(r"in ([^.]+?) the session-db MCP server is registered", text)
    assert match, f"{relative} is missing the generic session-db-registered conditional"
    normalised = re.sub(r"\s+", " ", match.group(1))
    named = {name.strip() for name in re.split(r",| and ", normalised) if name.strip()}
    tool_ids = {_PROSE_HARNESS_TO_TOOL_ID[name] for name in named}
    assert tool_ids == set(installers._MCP_HARNESSES), (
        f"{relative} names {tool_ids} but installers._MCP_HARNESSES is "
        f"{set(installers._MCP_HARNESSES)}"
    )
