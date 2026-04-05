"""Tmux pane capture and response extraction for evaluation scenarios."""

from __future__ import annotations

import logging
import re
import subprocess
import time

logger = logging.getLogger(__name__)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_RE.sub("", text)


def capture_pane_plain(target: str) -> str:
    """Capture full tmux pane content as plaintext.

    Args:
        target: A tmux target — pane ID (e.g. ``%0``) or session name.
            Prefer explicit pane IDs to avoid capturing the wrong pane.

    Uses tmux capture-pane with -p (stdout) and -S - (full history).
    Returns empty string if the pane/session doesn't exist.
    """
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", target, "-p", "-S", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.debug(
            "capture-pane failed for target=%r: rc=%d stderr=%r",
            target,
            result.returncode,
            result.stderr.strip(),
        )
        return ""
    logger.debug("capture-pane target=%r captured %d chars", target, len(result.stdout))
    return result.stdout


def send_keys(target: str, text: str) -> None:
    """Send text to a tmux pane via send-keys.

    Args:
        target: A tmux target — pane ID (e.g. ``%0``) or session name.
    """
    result = subprocess.run(
        ["tmux", "send-keys", "-t", target, text, "Enter"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "send-keys failed for target=%r: rc=%d stderr=%r",
            target,
            result.returncode,
            result.stderr.strip(),
        )
    else:
        logger.debug("send-keys target=%r sent %d chars", target, len(text))


def capture_response(
    target: str,
    prompt_text: str,
    timeout: int = 90,
    stable_seconds: int = 5,
) -> str:
    """Send a prompt and capture the agent's response.

    Two-phase capture designed for TUI agents (Claude Code uses Ink):
      Phase 1 — Wait for pane content to CHANGE from baseline (by value, not length).
                TUI agents re-render in place, so content may change without growing.
      Phase 2 — Wait for content to stabilise (N identical polls in a row).

    Returns the full pane content (minus baseline) after stabilisation.
    For TUI agents where scrollback doesn't grow, returns the full
    stable pane content stripped of ANSI codes.
    """
    logger.debug(
        "capture_response: target=%r prompt=%r timeout=%d",
        target,
        prompt_text[:80],
        timeout,
    )

    baseline = capture_pane_plain(target)
    logger.debug("baseline: %d chars", len(baseline))

    send_keys(target, prompt_text)

    content = baseline
    elapsed = 0

    # Phase 1: wait for content to CHANGE (not just grow — TUI agents re-render)
    for tick in range(timeout):
        time.sleep(1)
        elapsed = tick + 1
        content = capture_pane_plain(target)
        if content != baseline:
            logger.debug(
                "phase 1: content changed after %ds (baseline=%d, now=%d)",
                elapsed,
                len(baseline),
                len(content),
            )
            break
    else:
        logger.warning(
            "capture_response: no change for target=%r after %ds (baseline=%d chars)",
            target,
            timeout,
            len(baseline),
        )
        return ""

    # Phase 2: wait for stability (content stops changing)
    prev = content
    stable_count = 0
    remaining = timeout - elapsed

    for _tick in range(remaining):
        time.sleep(1)
        elapsed += 1
        content = capture_pane_plain(target)
        if content == prev:
            stable_count += 1
            if stable_count >= stable_seconds:
                logger.debug("phase 2: stable after %ds total", elapsed)
                break
        else:
            stable_count = 0
            prev = content

    # If scrollback grew, take the tail. If TUI re-rendered (same/shorter
    # length), return the full content — can't diff a re-render by position.
    new_content = content[len(baseline) :] if len(content) > len(baseline) else content

    result = strip_ansi(new_content).strip()

    if not result:
        logger.warning(
            "capture_response: empty after strip for target=%r",
            target,
        )
    else:
        logger.debug("capture_response: got %d chars of response", len(result))

    return result
