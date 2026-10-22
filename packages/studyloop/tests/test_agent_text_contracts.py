"""Contracts between the agent-facing text StudyLoop ships and the real product.

The mentor personas, skills and setup prompts under ``agents/`` are installed
into each harness verbatim, so a command they name is a command a learner's
agent will run. These tests hold that text to the code it describes:

* every ``studyloop ...`` command the text names must parse against the real
  Click tree (F-XCUT-10: the Kiro mentor named ``studyloop state`` and
  ``studyloop schedule``, which never existed);
* every ``mcp[cli]`` spec handed to ``uvx --from`` must carry the same version
  bound the pyproject declares (F-OPS-03);
* no file the installer projects into a harness carries developer-tool
  steering meant for agents working on this repository (F-OPS-05).
"""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from importlib import import_module
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO_ROOT / "agents"
STUDYLOOP_PYPROJECT = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"

# ---------------------------------------------------------------------------
# studyloop commands named in agent text parse against the real CLI
# ---------------------------------------------------------------------------

_INLINE_RE = re.compile(r"`(studyloop\s[^`]*)`")
_FENCED_RE = re.compile(r"^\s*\$?\s*(studyloop\s.*)$")
_SHELL_OPERATORS = frozenset({"|", "||", ">", ">>", "&&", ";", "&", "<"})
#: Tokens a prose example uses to say "and so on"; nothing after them is a command.
_ELISIONS = frozenset({"…", "..."})


def _command_text_files() -> list[Path]:
    files = sorted(AGENTS_DIR.rglob("*.md")) + sorted(AGENTS_DIR.rglob("*.json"))
    return [*files, REPO_ROOT / "docs" / "setup-guide.md"]


def _markdown_commands(text: str) -> list[tuple[int, str]]:
    """(line, command) for every inline-backticked or fenced ``studyloop ...``.

    Fenced lines ending in a backslash are joined with their continuation so a
    multi-line invocation is parsed as one command.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            match = _FENCED_RE.match(line)
            if match:
                start = i + 1
                joined = match.group(1)
                while joined.rstrip().endswith("\\") and i + 1 < len(lines):
                    i += 1
                    joined = joined.rstrip()[:-1] + " " + lines[i].strip()
                found.append((start, joined.strip()))
        else:
            found.extend((i + 1, m.group(1).strip()) for m in _INLINE_RE.finditer(line))
        i += 1
    return found


def _json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _json_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _json_strings(v)]
    return []


def _studyloop_command_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for path in _command_text_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if path.suffix == ".json":
            for text in _json_strings(json.loads(path.read_text(encoding="utf-8"))):
                cases.extend((f"{rel}:json", cmd) for _line, cmd in _markdown_commands(text))
        else:
            text = path.read_text(encoding="utf-8")
            cases.extend((f"{rel}:{line}", cmd) for line, cmd in _markdown_commands(text))
    return cases


def _load_cli_group() -> click.Group:
    """The Click group behind the ``studyloop`` entry point in pyproject."""
    target = tomllib.loads(STUDYLOOP_PYPROJECT.read_text())["project"]["scripts"]["studyloop"]
    module_name, attr_name = target.split(":", 1)
    group = getattr(import_module(module_name), attr_name)
    assert isinstance(group, click.Group), f"{target} is not a click.Group"
    return group


def _cli_args(command: str) -> list[str]:
    tokens = shlex.split(command, comments=True)
    assert tokens[0] == "studyloop", command
    args: list[str] = []
    for token in tokens[1:]:
        if token in _SHELL_OPERATORS or token in _ELISIONS:
            break
        args.append(token)
    return args


def _parse_problem(root: click.Group, args: list[str]) -> str | None:
    """Parse *args* the way Click would, descending into every subcommand.

    ``resilient_parsing`` keeps help/version callbacks, prompts and missing
    required arguments out of the way, but it also makes Click return ``None``
    for an unknown subcommand instead of raising, so that case is reported
    here explicitly. Unknown options still raise ``NoSuchOption``.
    """
    try:
        ctx = root.make_context("studyloop", list(args), resilient_parsing=True)
        while isinstance(ctx.command, click.Group):
            rest = [*ctx._protected_args, *ctx.args]
            if not rest:
                return None
            name, cmd, remaining = ctx.command.resolve_command(ctx, rest)
            if cmd is None or name is None:
                return f"No such command {rest[0]!r} under {ctx.command_path!r}"
            ctx = cmd.make_context(name, remaining, parent=ctx, resilient_parsing=True)
    except click.UsageError as exc:
        return f"{type(exc).__name__}: {exc.format_message()}"
    return None


def test_command_extraction_finds_the_agent_text() -> None:
    """Guard the extractor itself: an empty case list would pass vacuously."""
    cases = _studyloop_command_cases()
    assert len(cases) > 100
    assert any(loc.startswith("agents/kiro/") for loc, _cmd in cases)
    assert any(loc.startswith("docs/setup-guide.md") for loc, _cmd in cases)


def test_parser_reports_an_unknown_subcommand() -> None:
    """Positive control: the check must fail on a command that does not exist."""
    root = _load_cli_group()
    assert _parse_problem(root, ["sesion", "start"]) is not None
    assert _parse_problem(root, ["session", "strat"]) is not None
    assert _parse_problem(root, ["session", "start"]) is None


def test_every_studyloop_command_in_agent_files_parses() -> None:
    root = _load_cli_group()
    problems = []
    for location, command in _studyloop_command_cases():
        try:
            args = _cli_args(command)
        except ValueError as exc:
            problems.append(f"{location}: {command!r} -> could not tokenize: {exc}")
            continue
        problem = _parse_problem(root, args)
        if problem is not None:
            problems.append(f"{location}: {command!r} -> {problem}")
    assert problems == [], "\n".join(problems)


# ---------------------------------------------------------------------------
# uvx mcp[cli] specs carry the project's own version bound
# ---------------------------------------------------------------------------

_MCP_SPEC_RE = re.compile(r"mcp\[cli\][^\"'\s\]]*")
#: How far before a spec to look for the uvx / --from that makes it a resolver input.
_UVX_CONTEXT_CHARS = 60


def _pyproject_mcp_pin() -> str:
    extras = tomllib.loads(STUDYLOOP_PYPROJECT.read_text())["project"]["optional-dependencies"]
    (pin,) = extras["mcp"]
    assert pin.startswith("mcp[cli]"), pin
    return pin


def _uvx_mcp_spec_cases() -> list[tuple[str, str]]:
    """(location, spec) for every ``mcp[cli]...`` handed to ``uvx --from``."""
    paths = [p for p in sorted(AGENTS_DIR.rglob("*")) if p.is_file()]
    paths.append(REPO_ROOT / "docs" / "voice-output.md")
    cases: list[tuple[str, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in _MCP_SPEC_RE.finditer(text):
            before = text[max(0, match.start() - _UVX_CONTEXT_CHARS) : match.start()]
            if "--from" in before or "uvx" in before:
                line = text.count("\n", 0, match.start()) + 1
                cases.append((f"{rel}:{line}", match.group(0)))
    return cases


def test_uvx_mcp_spec_scan_finds_the_installed_kiro_agent() -> None:
    """Guard the scanner: the installed Kiro agent and the voice guide must be seen."""
    locations = [loc for loc, _spec in _uvx_mcp_spec_cases()]
    assert any(loc.startswith("agents/kiro/study-mentor.json:") for loc in locations)
    assert any(loc.startswith("docs/voice-output.md:") for loc in locations)


def test_uvx_mcp_specs_carry_the_pyproject_upper_bound() -> None:
    """F-OPS-03: every manifest pins ``mcp[cli]>=1.0.0,<2``; a bare ``mcp[cli]``
    given to ``uvx --from`` resolves whatever is newest instead, so the
    study-speak server runs against an MCP SDK the project never accepted."""
    pin = _pyproject_mcp_pin()
    unpinned = [f"{loc}: {spec}" for loc, spec in _uvx_mcp_spec_cases() if spec != pin]
    assert unpinned == [], f"expected {pin!r}:\n" + "\n".join(unpinned)


# ---------------------------------------------------------------------------
# installed mentor text carries no developer-tool steering
# ---------------------------------------------------------------------------


def _installed_repo_sources() -> list[Path]:
    """Every repository file ``studyloop install agents`` links into a harness."""
    from studyloop import installers

    specs = [spec for specs in installers._TOOL_LINKS.values() for spec in specs]
    specs.extend(installers._SHARED_LINKS)
    files: set[Path] = set()
    for spec in specs:
        if not spec.source.startswith("agents/"):
            continue  # hub-relative links (~/.agents/...) point back at these same sources
        source = REPO_ROOT / spec.source
        if source.is_dir():
            files.update(p for p in source.rglob("*") if p.is_file())
        elif source.is_file():
            files.add(source)
    return sorted(files)


def _learner_facing_sources() -> list[Path]:
    """Installed sources plus the per-session persona parts the launcher assembles.

    Council pass 3, D1: Codex and Grok Build no longer get a repo-root link, so
    ``agents/codex/AGENTS.md`` is not an installed source any more; what those
    harnesses actually read is built from ``agents/shared/personas/`` into each
    session directory. Both sets are learner-facing and are checked together.
    """
    files = set(_installed_repo_sources())
    personas = REPO_ROOT / "agents" / "shared" / "personas"
    files.update(p for p in personas.rglob("*") if p.is_file())
    tracked_codex = REPO_ROOT / "agents" / "codex" / "AGENTS.md"
    if tracked_codex.is_file():
        files.add(tracked_codex)
    return sorted(files)


def test_installed_sources_no_longer_include_a_repo_root_persona_link() -> None:
    """D1: nothing ``install agents`` links comes from or goes to the checkout root."""
    from studyloop import installers

    specs = [spec for specs in installers._TOOL_LINKS.values() for spec in specs]
    assert all("{repo_root}" not in spec.target for spec in specs)
    assert REPO_ROOT / "agents" / "shared" / "personas" / "study.md" in _learner_facing_sources()


def test_mentor_definitions_carry_no_developer_tool_steering() -> None:
    """F-OPS-05: the Codex and Grok Build learner persona ("a strict Socratic
    mentor, not a code assistant") carried a KiroGraph block telling the model
    to explore "this codebase" and to ask the learner to run `kirograph init
    --index`. No other harness's mentor had it. Checked across every
    learner-facing source, installed or assembled per session."""
    hits = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in _learner_facing_sources()
        if "kirograph" in p.read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert hits == []
