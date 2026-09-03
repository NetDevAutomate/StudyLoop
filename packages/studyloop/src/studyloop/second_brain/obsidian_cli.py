"""Optional adapter for the official Obsidian CLI.

Everything the second-brain layer does is achievable by writing files, and the
file writer is always what produces the final bytes. This adapter exists for the
two things files cannot do: let the learner's own Obsidian template and plugin
hooks fire when a note is first created, and add one link line to today's daily
note.

Two facts about the CLI shape every decision here:

* **It needs the desktop app running.** So its availability is a runtime
  question, answered by a probe, never an install-time assumption.
* **Its grammar is not versioned.** So the whole surface is one module — a
  grammar change costs one file — and every documented command line is exported
  as :data:`DOCUMENTED_COMMANDS` for the docs guard to compare against.

Every spawn uses an argv list with ``shell=False``, a timeout, and ``stdin``
closed. A vault name is learner-supplied text, so a shell string would make a
vault called ``My Notes; rm -rf ~`` a command injection; and this runs from an
agent's wind-down flow, where a subprocess that prompts would block a terminal
nobody is watching.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from studyloop.settings import SecondBrainConfig

logger = logging.getLogger(__name__)

CliMode = Literal["cli", "files"]

#: Long enough for a busy desktop app to answer, short enough that a hung one
#: does not hold up a publish the learner is waiting on.
PROBE_TIMEOUT_SECONDS = 10

#: The JavaScript the probe evaluates. Read-only: it asks which vault answered
#: and how many files it can see, and touches nothing.
_PROBE_SCRIPT = "JSON.stringify({vault: app.vault.getName(), files: app.vault.getFiles().length})"

#: The exact command forms the documentation quotes.
#:
#: A single constant because the CLI grammar is unversioned: a documented command
#: that no longer matches what this module builds is a promise the tool cannot
#: keep, and ``tests/test_second_brain_docs.py`` compares the guide's fenced
#: ``obsidian`` lines against this tuple.
DOCUMENTED_COMMANDS: tuple[str, ...] = (
    "obsidian eval '<script>' [vault=<name>]",
    "obsidian create name=<path> [template=<name>] content=<text> [vault=<name>]",
    "obsidian daily:append content=<text> [vault=<name>]",
)

#: Warn at most once per process when ``use_cli: on`` cannot be honoured.
#: Repeating it on every publish is how a real signal becomes noise a learner
#: filters out.
_warned_unavailable = False


def reset_warning_state() -> None:
    """Clear the warn-once latch. For tests only."""
    global _warned_unavailable
    _warned_unavailable = False


def _binary() -> str | None:
    return shutil.which("obsidian")


def _vault_argument(config: SecondBrainConfig) -> list[str]:
    return [f"vault={config.vault_name}"] if config.vault_name else []


def _spawn(argv: list[str], *, timeout: int = PROBE_TIMEOUT_SECONDS):
    return subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def _probe(config: SecondBrainConfig) -> bool:
    """True when a running Obsidian answers for the expected vault.

    A mismatched vault name is treated as a failure. Obsidian can have several
    vaults open, and a probe satisfied by whichever one happens to be focused
    would write the learner's study notes into the wrong vault — a worse outcome
    than not using the CLI at all.
    """
    argv = ["obsidian", "eval", _PROBE_SCRIPT, *_vault_argument(config)]
    try:
        completed = _spawn(argv)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("obsidian probe failed to run: %s", exc)
        return False
    if completed.returncode != 0:
        logger.debug("obsidian probe exited %s", completed.returncode)
        return False
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        logger.debug("obsidian probe returned output that is not JSON")
        return False
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("vault"), str) or not isinstance(payload.get("files"), int):
        return False
    if config.vault_name and payload["vault"] != config.vault_name:
        logger.debug(
            "obsidian answered for vault %r, not the configured %r",
            payload["vault"],
            config.vault_name,
        )
        return False
    return True


def resolve_cli_mode(config: SecondBrainConfig) -> CliMode:
    """The one decision point: does this publish use the CLI, or files?

    Reported by ``studyloop brain status`` and ``studyloop doctor`` as the
    EFFECTIVE mode, because ``auto`` is not an answer a learner can act on.
    """
    global _warned_unavailable

    if config.use_cli == "off":
        return "files"

    if _binary() is None:
        if config.use_cli == "on" and not _warned_unavailable:
            _warned_unavailable = True
            logger.warning(
                "second_brain.use_cli is 'on' but the obsidian CLI is not on PATH; "
                "writing files instead."
            )
        else:
            logger.debug("obsidian CLI not on PATH; writing files")
        return "files"

    if _probe(config):
        return "cli"

    if config.use_cli == "on" and not _warned_unavailable:
        _warned_unavailable = True
        logger.warning(
            "second_brain.use_cli is 'on' but Obsidian did not answer (is the desktop "
            "app running?); writing files instead."
        )
    else:
        logger.debug("obsidian did not answer the probe; writing files")
    return "files"


def create_note(config: SecondBrainConfig, relative: str, content: str) -> bool:
    """Ask Obsidian to create a note, so the learner's own hooks fire.

    Returns ``False`` on any failure rather than raising: the caller writes the
    canonical bytes with the file writer immediately afterwards either way, so a
    CLI failure costs the template hook and nothing else.
    """
    argv = ["obsidian", "create", f"name={relative}"]
    if config.template:
        argv.append(f"template={config.template}")
    argv.append(f"content={content}")
    argv.extend(_vault_argument(config))
    try:
        completed = _spawn(argv)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("obsidian create failed to run: %s", exc)
        return False
    if completed.returncode != 0:
        logger.debug("obsidian create exited %s: %s", completed.returncode, completed.stderr)
        return False
    return True


def _stamp_path(state_dir: Path) -> Path:
    return state_dir / "second-brain-daily-note.stamp"


def daily_append(config: SecondBrainConfig, state_dir: Path) -> bool:
    """Append one link line to today's daily note, at most once a day.

    This is the only write into a note the learner owns, which is why it needs a
    second explicit opt-in (``daily_note: true``) on top of the CLI being usable
    at all, and why it is capped at one line per calendar day.

    The once-a-day stamp lives in the state directory, never in the vault: a
    marker file inside the vault would itself be an unowned StudyLoop write into
    the learner's notes, which is the exact thing this feature promises not to do.
    """
    if not config.daily_note:
        return False
    if resolve_cli_mode(config) != "cli":
        return False

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stamp = _stamp_path(state_dir)
    if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == today:
        logger.debug("daily note already linked today")
        return False

    argv = [
        "obsidian",
        "daily:append",
        "content=- [[Study/Today|StudyLoop: today's study]]",
        *_vault_argument(config),
    ]
    try:
        completed = _spawn(argv)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("obsidian daily:append failed to run: %s", exc)
        return False
    if completed.returncode != 0:
        logger.debug("obsidian daily:append exited %s", completed.returncode)
        return False

    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{today}\n", encoding="utf-8")
    os.chmod(stamp, 0o644)
    return True


__all__ = [
    "DOCUMENTED_COMMANDS",
    "PROBE_TIMEOUT_SECONDS",
    "CliMode",
    "create_note",
    "daily_append",
    "reset_warning_state",
    "resolve_cli_mode",
]
