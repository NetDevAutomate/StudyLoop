"""Guard the CLI reference against stale ``studyloop`` command examples."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import cast

import click

from studyloop.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_REFERENCE = REPO_ROOT / "docs" / "cli-reference.md"


def _bash_blocks(markdown: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", markdown, flags=re.DOTALL)


def _strip_prompt(line: str) -> str:
    stripped = line.strip()
    for prompt in ("$ ", "> "):
        if stripped.startswith(prompt):
            return stripped[len(prompt) :].strip()
    return stripped


def _logical_lines(block: str) -> list[str]:
    lines: list[str] = []
    current = ""
    for raw_line in block.splitlines():
        line = _strip_prompt(raw_line)
        if not line or line.startswith("#"):
            continue

        continued = line.endswith("\\")
        line = line[:-1].rstrip() if continued else line
        current = f"{current} {line}".strip() if current else line

        if not continued:
            lines.append(current)
            current = ""

    if current:
        lines.append(current)
    return lines


def _studyloop_examples() -> list[list[str]]:
    examples: list[list[str]] = []
    for block in _bash_blocks(CLI_REFERENCE.read_text(encoding="utf-8")):
        for line in _logical_lines(block):
            if not line.startswith("studyloop "):
                continue
            tokens = shlex.split(line, comments=True)
            if tokens and tokens[0] == "studyloop":
                examples.append(tokens[1:])
    return examples


def _known_command_prefix(tokens: list[str]) -> tuple[str, ...]:
    command = cast("click.Command", cli)
    prefix: list[str] = []
    for token in tokens:
        if not isinstance(command, click.Group):
            break
        if token.startswith("-"):
            break
        ctx = click.Context(command)
        child = command.get_command(ctx, token)
        if child is None:
            break
        prefix.append(token)
        command = child
    return tuple(prefix)


def _has_unknown_group_subcommand(tokens: list[str]) -> bool:
    command = cast("click.Command", cli)
    for token in tokens:
        if not isinstance(command, click.Group):
            return False
        if token.startswith("-"):
            return False

        ctx = click.Context(command)
        child = command.get_command(ctx, token)
        if child is None:
            return True
        command = child
    # A bare group is normally a documentation error — `studyloop content` on its
    # own does nothing. The exception is a group declared with
    # invoke_without_command=True (e.g. `studyloop focus`, which prints the
    # current focus topics), where bare invocation is a real, exit-0 command and
    # therefore legitimate to document.
    if isinstance(command, click.Group):
        return not command.invoke_without_command
    return False


def test_known_command_prefix_common_examples() -> None:
    assert _known_command_prefix(["content", "generate-cards", "./notes"]) == (
        "content",
        "generate-cards",
    )
    assert _known_command_prefix(["doctor", "--fix"]) == ("doctor",)
    assert _known_command_prefix(["session", "start", "--topic", "Python"]) == (
        "session",
        "start",
    )


def test_cli_reference_studyloop_commands_exist() -> None:
    examples = _studyloop_examples()

    assert examples, "No studyloop examples found in docs/cli-reference.md"

    missing = [
        "studyloop " + " ".join(tokens)
        for tokens in examples
        if not _known_command_prefix(tokens) or _has_unknown_group_subcommand(tokens)
    ]
    assert missing == []
