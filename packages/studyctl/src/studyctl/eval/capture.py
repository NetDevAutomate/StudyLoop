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

    Args:
        target: A tmux target — pane ID (e.g. ``%0``) preferred over session name.
        prompt_text: The text to send to the agent.
        timeout: Maximum seconds to wait for a response.
        stable_seconds: How many consecutive unchanged polls count as "stable".

    1. Record pane content before sending (baseline)
    2. Send prompt via send-keys
    3. Poll pane until output stabilises (stable_seconds of no change)
    4. Extract new content (diff from baseline)
    5. Strip ANSI codes

    Returns the new content added after the prompt was sent.
    Returns empty string on timeout or if no new content appears.
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

    prev = baseline
    stable_count = 0
    content = baseline

    for tick in range(timeout):
        time.sleep(1)
        content = capture_pane_plain(target)
        if content == prev:
            stable_count += 1
            if stable_count >= stable_seconds:
                new_chars = len(content) - len(baseline)
                logger.debug("stable after %d ticks (%d chars new)", tick + 1, new_chars)
                break
        else:
            stable_count = 0
            prev = content

    new_content = content[len(baseline) :] if len(content) > len(baseline) else ""
    result = strip_ansi(new_content).strip()

    if not result:
        logger.warning(
            "capture_response: empty result for target=%r after %ds (baseline=%d, final=%d)",
            target,
            timeout,
            len(baseline),
            len(content),
        )
    else:
        logger.debug("capture_response: got %d chars of new content", len(result))

    return result
