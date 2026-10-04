"""``studyloop module new <id>`` -- scaffold a module that passes ``module check``.

Module-contract v1 (proposal §5.1, §7), lane C. :func:`scaffold_module` writes the §5.1
layout with one offline, ``echo``-based drill: ``scripts/check.sh`` prints ``ready`` and exits
0 without touching the network, Docker or kind, so the scaffold runs end to end on any POSIX
host and is the fixture the drill runner's own tests use. Everything written is data: the
only executable is the check script the module author is expected to replace.

The scaffold declares ``capabilities: [check]``, no prerequisites and a ``workdir`` target. It
ships one offline test of its own (``tests/check.sh``, a shell script -- MC012 forbids Python
in a module) that runs the drill's check and asserts its output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from studyloop.content.schemas import SLUG_PATTERN

CONTRACT_VERSION = 1
"""The module-contract version the scaffold targets."""

_SLUG = re.compile(SLUG_PATTERN)


class ScaffoldError(ValueError):
    """The scaffold cannot be written: bad id or an occupied destination."""


def _title_from_id(module_id: str) -> str:
    return module_id.replace("-", " ").strip().capitalize()


def _manifest_yaml(module_id: str, title: str, topic: str, author: str) -> str:
    # Written by hand rather than yaml.dump so the file reads like the §5.2 example: key
    # order preserved, comments pointing at the contract, flow-style capabilities.
    return (
        f"id: {module_id}\n"
        f"contract: {CONTRACT_VERSION}\n"
        "version: 0.1.0\n"
        f"title: {json.dumps(title)}\n"
        f"topic: {topic}\n"
        "license: MIT\n"
        "maintainers:\n"
        f"  - name: {json.dumps(author)}\n"
        "prerequisites: []        # ids from core's enum: docker | kind | kubectl\n"
        "capabilities: [check]    # add setup / cleanup only when a deck phase uses them\n"
        "target:\n"
        "  kind: workdir          # or kubeconfig-context for a core-created disposable cluster\n"
    )


def _deck(module_id: str) -> dict[str, object]:
    return {
        "id": "getting-started",
        "title": "Getting started",
        "tasks": [
            {
                "id": "ready-01",
                "taskType": "apply",
                "prompt": "Print the word `ready` to standard output.",
                "successCriteria": ["The word `ready` is printed"],
                "expectedLearningOutcome": "Run a command and read its output.",
                "hint": "Which command prints its arguments?",
                "solution": "echo ready",
                "scaffolding": "guided",
                "mentorNotes": (
                    "If they reach for printf, ask what echo would have done. "
                    f"Replace this drill with the first real one of {module_id}."
                ),
                "verification": {
                    "kind": "command",
                    "successCriteria": ["Check script exits 0"],
                    "command": "scripts/check.sh",
                    "timeoutSeconds": 10,
                },
            }
        ],
    }


_CHECK_SH = """#!/bin/sh
# Offline check for ready-01: prints `ready` and exits 0. Needs nothing but a POSIX shell.
# Exit codes (proposal §5.5): 0 = passed, 1 = task not complete, >= 2 = could not run.
echo ready
exit 0
"""

_TEST_SH = """#!/bin/sh
# The module's own offline test: the drill's check must print `ready` and exit 0.
# Run from the module root: sh tests/check.sh
set -eu
cd "$(dirname "$0")/.."
out="$(scripts/check.sh)"
[ "$out" = "ready" ] || { echo "expected 'ready', got '$out'" >&2; exit 1; }
echo "ok: scripts/check.sh printed ready"
"""


def _readme(module_id: str, title: str) -> str:
    return (
        f"# {title}\n\n"
        f"A StudyLoop module (contract {CONTRACT_VERSION}). Replace the `getting-started` deck "
        "with real drills and keep the four sections below accurate: `studyloop module check .` "
        "requires them.\n\n"
        "## Prerequisites\n\n"
        "None beyond a POSIX shell. Declare tools in `module.yaml` `prerequisites` (ids from "
        "StudyLoop's enum: `docker`, `kind`, `kubectl`).\n\n"
        "## What runs\n\n"
        "`scripts/check.sh` prints `ready` and exits 0. Every phase command is one executable "
        "under `scripts/` plus literal arguments, run by StudyLoop with `shell=False` after "
        "the learner consents to that exact command.\n\n"
        "## Data collected\n\n"
        "Only each check's exit code and captured output, kept for the attempt and delivered "
        "to the mentor as labelled data. Nothing is written to the learner's history.\n\n"
        "## Limits\n\n"
        f"The scaffolded drill teaches nothing yet; it exists so `{module_id}` passes "
        "`module check` and runs end to end before the first real drill lands.\n"
    )


def _mentor_brief(title: str) -> str:
    return (
        f"# Mentor brief: {title}\n\n"
        "This brief is composed into the mentor's context when a drill from this module is "
        "live. It is advisory and never shown to the learner.\n\n"
        "## Misconceptions to watch\n\n"
        "- The learner types `echo` and expects something other than their own word back. "
        "Ask what they expected to see before saying anything.\n\n"
        "## What not to reveal, and when\n\n"
        '- Do not reveal `echo ready` unprompted. On the "just show me" path, explain '
        "afterwards why the argument comes back unchanged.\n"
    )


def _license(author: str) -> str:
    return (
        "MIT License\n\n"
        f"Copyright (c) {author}\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy of this "
        'software and associated documentation files (the "Software"), to deal in the '
        "Software without restriction, including without limitation the rights to use, copy, "
        "modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, "
        "and to permit persons to whom the Software is furnished to do so, subject to the "
        "following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all copies "
        "or substantial portions of the Software.\n\n"
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, '
        "INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A "
        "PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT "
        "HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF "
        "CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE "
        "OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n"
    )


_CHANGELOG = """# Changelog

## 0.1.0

- Scaffolded with `studyloop module new`: one offline `ready-01` drill.
"""


def scaffold_module(
    destination: Path,
    module_id: str,
    *,
    title: str | None = None,
    topic: str = "shell",
    author: str = "Module author",
) -> Path:
    """Write a conforming module for ``module_id`` into ``destination`` and return it.

    ``destination`` must not exist or must be an empty directory; ``module_id`` must be a
    slug (:data:`studyloop.content.schemas.SLUG_PATTERN`). Raises :class:`ScaffoldError`
    otherwise, before anything is written.
    """
    if not _SLUG.fullmatch(module_id):
        raise ScaffoldError(
            f"{module_id!r} is not a module id: lowercase letters, digits and hyphens, "
            "starting with a letter or digit, at most 63 characters"
        )
    destination = Path(destination)
    if destination.exists():
        if not destination.is_dir():
            raise ScaffoldError(f"{destination} exists and is not a directory")
        if any(destination.iterdir()):
            raise ScaffoldError(f"{destination} is not empty; refusing to scaffold into it")
    title = title or _title_from_id(module_id)

    files: dict[str, str] = {
        "module.yaml": _manifest_yaml(module_id, title, topic, author),
        "decks/getting-started.json": json.dumps(_deck(module_id), indent=2) + "\n",
        "scripts/check.sh": _CHECK_SH,
        "tests/check.sh": _TEST_SH,
        "mentor/brief.md": _mentor_brief(title),
        "README.md": _readme(module_id, title),
        "LICENSE": _license(author),
        "CHANGELOG.md": _CHANGELOG,
    }
    for relative, content in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for script in ("scripts/check.sh", "tests/check.sh"):
        (destination / script).chmod(0o755)
    return destination
