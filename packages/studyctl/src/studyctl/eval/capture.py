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

    Two-phase capture:
      Phase 1 — Wait for content to grow past baseline (agent is processing).
      Phase 2 — Wait for content to stabilise (agent finished responding).

    This prevents false-stable returns when the agent is still initializing.

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
    baseline_len = len(baseline)
    logger.debug("baseline: %d chars", baseline_len)

    send_keys(target, prompt_text)

    content = baseline
    elapsed = 0

    # Phase 1: wait for ANY new content (agent may be initializing)
    for tick in range(timeout):
        time.sleep(1)
        elapsed = tick + 1
        content = capture_pane_plain(target)
        if len(content) > baseline_len:
            logger.debug(
                "phase 1: new content after %ds (+%d chars)",
                elapsed,
                len(content) - baseline_len,
            )
            break
    else:
        logger.warning(
            "capture_response: no new content for target=%r after %ds (baseline=%d, final=%d)",
            target,
            timeout,
            baseline_len,
            len(content),
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
                logger.debug(
                    "phase 2: stable after %ds total (%d chars new)",
                    elapsed,
                    len(content) - baseline_len,
                )
                break
        else:
            stable_count = 0
            prev = content

    new_content = content[baseline_len:] if len(content) > baseline_len else ""
    result = strip_ansi(new_content).strip()

    if not result:
        logger.warning(
            "capture_response: empty after strip for target=%r (raw new=%d chars, stripped to 0)",
            target,
            len(new_content),
        )
    else:
        logger.debug("capture_response: got %d chars of new content", len(result))

    return result
