"""Contracts between the agent-facing text StudyLoop ships and the real product.

The mentor personas, skills and setup prompts under ``agents/`` are installed
into each harness verbatim, so a command they name is a command a learner's
agent will run. These tests hold that text to the code it describes:

* every ``studyloop ...`` command the text names must parse against the real
  Click tree (F-XCUT-10: the Kiro mentor named ``studyloop state`` and
  ``studyloop schedule``, which never existed).
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
