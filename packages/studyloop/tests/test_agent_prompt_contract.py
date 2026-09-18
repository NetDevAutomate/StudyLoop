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

import click
import pytest
import typer
from _sessions_db_template import seed_sessions_db
from typer.testing import CliRunner

runner = CliRunner()


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/manifest.json").exists():
        root = root.parent
    assert (root / "agents/manifest.json").exists()
    return root


def _normalised(text: str) -> str:
    return " ".join(text.split())


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
    "OpenCode": "opencode",
    "Grok Build": "grok",
}


@pytest.mark.parametrize("relative", ["agents/pi/AGENTS.md"])
def test_memory_search_is_hedged_with_a_session_query_fallback(relative: str) -> None:
    """pi never gets session-db-mcp (installers._MCP_HARNESSES; pi has no MCP

    by design), so memory_search must name the CLI fallback near the call,
    exactly as agents/skills/studyloop-session-memory/SKILL.md phrases the
    pattern elsewhere (MCP tool when connected, CLI fallback otherwise).
    OpenCode moved out of this set once `studyloop install agents --tool
    opencode` started registering session-db-mcp globally
    (L8-mcp-opencode-grok) -- see
    test_opencode_get_concept_context_is_wired_and_not_hedged below for its
    unhedged counterpart.
    """
    import studyloop.installers as installers

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


def test_opencode_memory_search_is_wired_and_not_hedged() -> None:
    """OpenCode is now in installers._MCP_HARNESSES (L8-mcp-opencode-grok):

    `studyloop install agents --tool opencode` registers session-db-mcp
    globally, so memory_search must not carry the "only when connected"
    session-query hedge there any more.
    """
    import studyloop.installers as installers

    assert "opencode" in installers._MCP_HARNESSES

    text = (_repo_root() / "agents/opencode/study-mentor.md").read_text(encoding="utf-8")
    match = re.search(r"memory_search", text)
    assert match, "agents/opencode/study-mentor.md no longer mentions memory_search"
    window = text[match.end() : match.end() + 80]
    assert "session-query" not in window, (
        f"memory_search is wired for OpenCode via session-db-mcp; it should not "
        f"carry a CLI-fallback hedge immediately after the call: {window!r}"
    )


def test_agents_md_is_the_codex_symlink() -> None:
    repo_root = _repo_root()
    root_agents = repo_root / "AGENTS.md"
    codex_agents = repo_root / "agents/codex/AGENTS.md"
    assert root_agents.read_text(encoding="utf-8") == codex_agents.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# L7 -- study-plan-architect: ONE canonical body, carried verbatim by every
# native harness definition after its own harness-specific header (frontmatter
# for Claude/OpenCode, nothing at all for Kiro), exactly like AGENTS.md ==
# agents/codex/AGENTS.md above.
# ---------------------------------------------------------------------------

_PLAN_ARCHITECT_CANONICAL = "agents/shared/personas/plan-architect.md"


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---\\n...\\n---\\n`` YAML frontmatter block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    assert end != -1, "frontmatter opened with '---' but never closed"
    return text[end + len("\n---\n") :]


@pytest.mark.parametrize(
    "relative",
    [
        "agents/claude/study-plan-architect.md",
        "agents/opencode/study-plan-architect.md",
        "agents/kiro/study-plan-architect/persona.md",
    ],
)
def test_plan_architect_native_files_carry_the_canonical_body_verbatim(relative: str) -> None:
    repo_root = _repo_root()
    canonical = (repo_root / _PLAN_ARCHITECT_CANONICAL).read_text(encoding="utf-8").lstrip("\n")
    body = _strip_frontmatter((repo_root / relative).read_text(encoding="utf-8")).lstrip("\n")
    assert body == canonical, f"{relative} body has drifted from {_PLAN_ARCHITECT_CANONICAL}"


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


# ---------------------------------------------------------------------------
# W22 -- agents/opencode/mcp.json is orphaned and wrong-schema; delete it and
# stop pointing users at it.
# ---------------------------------------------------------------------------


def test_opencode_mcp_json_does_not_exist_and_is_unreferenced() -> None:
    repo_root = _repo_root()
    assert not (repo_root / "agents/opencode/mcp.json").exists()

    for path in _agents_text_files():
        text = path.read_text(encoding="utf-8")
        assert "opencode/mcp.json" not in text, f"{path} still references opencode/mcp.json"

    for path in (repo_root / "docs").rglob("*.md"):
        if "receipts" in path.parts:
            continue  # frozen historical evidence, not a live doc
        text = path.read_text(encoding="utf-8")
        assert "opencode/mcp.json" not in text, f"{path} still references opencode/mcp.json"


# ---------------------------------------------------------------------------
# W23 -- study-plan-architect is not wired into any installer; stop telling
# scripts/install.sh users to start it.
# ---------------------------------------------------------------------------


def test_install_sh_advertises_the_shipped_study_plan_architect() -> None:
    """L7: study-plan-architect is now wired into every installer link table
    (installers._TOOL_LINKS), so install.sh's next-steps text names the real
    launch command instead of staying silent about it."""
    import studyloop.installers as installers

    assert "study-plan-architect" in installers._TOOL_LINKS["claude"][1].source

    text = (_repo_root() / "scripts/install.sh").read_text(encoding="utf-8")
    assert "study-plan-architect" in text
    assert "plan architect" in text


def test_agent_install_doc_flags_study_plan_architect_as_installed() -> None:
    text = _normalised((_repo_root() / "docs/agent-install.md").read_text(encoding="utf-8"))
    assert "study-plan-architect" in text
    match = re.search(r"[^.]*study-plan-architect[^.]*\.", text)
    assert match, "docs/agent-install.md mentions study-plan-architect without a sentence"
    assert not re.search(r"draft|not (?:yet )?install", match.group(0), re.IGNORECASE), (
        f"docs/agent-install.md still says study-plan-architect is not installed: "
        f"{match.group(0)!r}"
    )


def test_no_in_scope_doc_still_says_the_plan_architect_personas_are_not_installed() -> None:
    """The L5 sentence flagging the three persona files as drafts must be gone
    from every doc this lane touches, now that installers._TOOL_LINKS ships
    them."""
    for relative in ("docs/agent-install.md", "docs/study-plans.md"):
        text = (_repo_root() / relative).read_text(encoding="utf-8")
        assert "drafts, not yet wired into any installer" not in text, relative


@pytest.mark.parametrize("relative", ["docs/agent-install.md", "docs/study-plans.md"])
def test_plan_architect_docs_name_the_flow(relative: str) -> None:
    text = (_repo_root() / relative).read_text(encoding="utf-8")
    assert "plan-architect" in text or "plan architect" in text


def test_cli_reference_names_the_plan_architect_mode_and_command() -> None:
    text = (_repo_root() / "docs/cli-reference.md").read_text(encoding="utf-8")
    assert "plan-architect" in text
    assert "plan architect" in text


# ---------------------------------------------------------------------------
# W15 -- validated knowledge bridges persist to the sessions database, never
# to config.yaml (settings.py's KnowledgeDomainsConfig has no bridges field).
# ---------------------------------------------------------------------------


def test_bridge_add_persists_to_the_database_not_config_yaml(tmp_path, monkeypatch) -> None:
    from click.testing import CliRunner as ClickCliRunner

    from studyloop.cli import cli
    from studyloop.history.bridges import get_bridges

    click_runner = ClickCliRunner()

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "knowledge_domains:\n"
        "  primary: networking\n"
        "  anchors:\n"
        "    - concept: ECMP load balancing\n"
        "      comfort: 10\n"
        "  bridges: []  # populated dynamically via studyloop bridge add\n"
    )
    before = config_path.read_bytes()
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    seed_sessions_db(tmp_path / "sessions.db", monkeypatch)

    result = click_runner.invoke(
        cli,
        [
            "bridge",
            "add",
            "ECMP load balancing",
            "-s",
            "networking",
            "Spark partition distribution",
            "-t",
            "spark",
            "-m",
            "both distribute work across parallel processors",
        ],
    )
    assert result.exit_code == 0, result.output

    assert config_path.read_bytes() == before, "bridge add must never touch config.yaml"
    bridges = get_bridges(source_domain="networking")
    assert any(b["target_concept"] == "Spark partition distribution" for b in bridges), bridges


def test_knowledge_bridging_doc_sample_config_matches_the_real_schema() -> None:
    """The sample config.yaml block must not invent a ``bridges`` key, and
    Step 4 must name the function that actually persists a bridge.

    Pinning W15: bridges live in the sessions database (``record_bridge`` in
    ``history/bridges.py``), never in ``KnowledgeDomainsConfig``.
    """
    import dataclasses
    import inspect

    import yaml

    from studyloop import settings
    from studyloop.history import bridges as bridges_module

    model_fields = {f.name for f in dataclasses.fields(settings.KnowledgeDomainsConfig)}

    text = (_repo_root() / "agents/shared/knowledge-bridging.md").read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert match, "knowledge-bridging.md should have a fenced yaml sample config"
    sample = yaml.safe_load(match.group(1))
    sample_keys = set(sample["knowledge_domains"])
    assert sample_keys <= model_fields, (
        f"sample config keys {sample_keys - model_fields} are not real fields of "
        f"KnowledgeDomainsConfig {model_fields}"
    )

    persist_fns = [
        name
        for name, _ in inspect.getmembers(bridges_module, inspect.isfunction)
        if name.startswith("record_")
    ]
    assert persist_fns, "expected a record_* persistence function in history/bridges.py"

    step_four = text.split("**Step 4: Persist**", 1)[1]
    assert any(fn in step_four for fn in persist_fns), (
        f"Step 4: Persist should name the real persistence function {persist_fns}"
    )


# ---------------------------------------------------------------------------
# W16 -- record_plan_learning is a real MCP write path for plans; the doc
# must not claim there are none.
# ---------------------------------------------------------------------------


def test_study_plans_doc_does_not_deny_the_real_plan_mcp_tool() -> None:
    import inspect

    from studyloop.mcp import tools as mcp_tools

    source = inspect.getsource(mcp_tools)
    tool_functions = re.findall(r"@tool\(\)\s+def (\w+)\(([^)]*)\)", source)
    plan_tools = [name for name, params in tool_functions if "plan_id" in params]
    assert plan_tools, "expected at least one @tool() operating on plan_id"

    text = (_repo_root() / "docs/study-plans.md").read_text(encoding="utf-8")
    assert "no study-plan MCP tools" not in text, (
        f"docs/study-plans.md denies study-plan MCP tools but {plan_tools} exist"
    )
    assert any(tool in text for tool in plan_tools), (
        f"docs/study-plans.md should name the real plan-write tool {plan_tools}"
    )


# ---------------------------------------------------------------------------
# W42 -- orphaned reference script + leftover scratch text
# ---------------------------------------------------------------------------


def test_claude_session_export_hook_matches_export_hook_command() -> None:
    """agents/claude/hooks/session-export.sh is not read by any install path
    (installers.install_claude_stop_hook writes the hook command inline via
    export_hook_command); kept only as a reference copy, so it must stay in
    sync with the real generator or it will silently mislead a reader."""
    import studyloop.installers as installers

    text = (_repo_root() / "agents/claude/hooks/session-export.sh").read_text(encoding="utf-8")
    assert installers.export_hook_command("--claude-only") in text


@pytest.mark.parametrize(
    "relative", ["agents/shared/personas/study.md", "agents/shared/personas/co-study.md"]
)
def test_persona_files_start_with_their_mode_heading(relative: str) -> None:
    path = _repo_root() / relative
    text = path.read_text(encoding="utf-8")
    first_line = next(line for line in text.splitlines() if line.strip())
    stem = path.stem  # e.g. "co-study"
    expected_mode = "-".join(word.capitalize() for word in stem.split("-")) + " Mode"
    assert first_line.startswith(f"# {expected_mode}"), (
        f"{relative} must start with '# {expected_mode}', got: {first_line!r}"
    )


# ---------------------------------------------------------------------------
# L7 (d) -- prompt contract: every ``studyloop <command> [<sub>]`` the
# canonical study-plan-architect body instructs resolves to a REGISTERED
# click command, every ``--flag`` it uses is a declared option of that
# command, and the positional-argument count in the example is consistent
# with that command's real click.Argument params. Checking the canonical
# file also covers the three native definitions, since the sync test above
# pins them byte-identical to it after their header.
# ---------------------------------------------------------------------------

_PLAN_ARCHITECT_INVOCATION_RE = re.compile(r"^\$?\s*studyloop\b")


def _plan_architect_invocations() -> list[tuple[int, str]]:
    text = (_repo_root() / _PLAN_ARCHITECT_CANONICAL).read_text(encoding="utf-8")
    found: list[tuple[int, str]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        candidates = re.findall(r"`([^`]+)`", raw)
        if not candidates:
            stripped = raw.strip()
            if _PLAN_ARCHITECT_INVOCATION_RE.match(stripped):
                candidates = [stripped]
        for candidate in candidates:
            candidate = candidate.strip()
            if _PLAN_ARCHITECT_INVOCATION_RE.match(candidate):
                found.append((line_no, candidate))
    return found


def _plan_architect_invocation_params() -> list:
    return [
        pytest.param(line_no, example, id=f"{line_no}:{example}")
        for line_no, example in _plan_architect_invocations()
    ]


def _option_takes_a_value(cmd, opt_string: str) -> bool:
    for param in cmd.params:
        if isinstance(param, click.Option) and opt_string in (
            tuple(param.opts) + tuple(param.secondary_opts)
        ):
            return not param.is_flag
    return False


def test_plan_architect_names_at_least_one_command_example() -> None:
    assert _plan_architect_invocations(), "canonical plan-architect body names no commands at all"


@pytest.mark.parametrize("line_no, example", _plan_architect_invocation_params())
def test_plan_architect_invocation_resolves_with_matching_positional_count(
    line_no: int, example: str
) -> None:
    from test_docs_drift import _cut_at_shell_metachar, _declared_option_strings, _load_cli_group

    root = _load_cli_group()
    root_ctx = click.Context(root, info_name="studyloop")

    cut = _cut_at_shell_metachar(example)
    tokens = shlex.split(cut, comments=True)
    assert tokens and tokens[0] == "studyloop", f"line {line_no}: not a studyloop invocation"

    current: click.Command = root
    current_ctx = root_ctx
    still_descending = True
    positionals: list[str] = []
    skip_next = False

    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            opt = token.split("=", 1)[0] if "=" in token else token
            declared = _declared_option_strings(current)
            assert opt in declared, (
                f"line {line_no}: {opt!r} is not a declared option of "
                f"{current.name!r} ({example!r})"
            )
            if "=" not in token and _option_takes_a_value(current, opt):
                skip_next = True
            continue
        if still_descending and isinstance(current, click.Group):
            sub = current.get_command(current_ctx, token)
            if sub is not None:
                current_ctx = click.Context(sub, parent=current_ctx, info_name=token)
                current = sub
                continue
            still_descending = False
        else:
            still_descending = False
        positionals.append(token)

    argument_params = [p for p in current.params if isinstance(p, click.Argument)]
    required = sum(1 for p in argument_params if p.required)
    total = len(argument_params)
    assert required <= len(positionals) <= total, (
        f"line {line_no}: {example!r} resolved to {current.name!r} with "
        f"{len(positionals)} positional token(s) ({positionals!r}) but it declares "
        f"{required}..{total} click.Argument param(s)"
    )
