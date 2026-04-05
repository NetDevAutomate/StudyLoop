"""Tmux pane capture and response extraction for evaluation scenarios."""

from __future__ import annotations

import re
import subprocess
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_RE.sub("", text)


def capture_pane_plain(session_name: str) -> str:
    """Capture full tmux pane content as plaintext.

    Uses tmux capture-pane with -p (stdout) and -S - (full history).
    Returns empty string if the pane/session doesn't exist.
    """
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def send_keys(session_name: str, text: str) -> None:
    """Send text to a tmux pane via send-keys."""
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, text, "Enter"],
        capture_output=True,
        check=False,
    )


def capture_response(
    session_name: str,
    prompt_text: str,
    timeout: int = 90,
    stable_seconds: int = 5,
) -> str:
    """Send a prompt and capture the agent's response.

    1. Record pane content before sending (baseline)
    2. Send prompt via send-keys
    3. Poll pane until output stabilises (stable_seconds of no change)
    4. Extract new content (diff from baseline)
    5. Strip ANSI codes

    Returns the new content added after the prompt was sent.
    Returns empty string on timeout or if no new content appears.
    """
    baseline = capture_pane_plain(session_name)
    send_keys(session_name, prompt_text)

    prev = baseline
    stable_count = 0
    content = baseline

    for _ in range(timeout):
        time.sleep(1)
        content = capture_pane_plain(session_name)
        if content == prev:
            stable_count += 1
            if stable_count >= stable_seconds:
                break
        else:
            stable_count = 0
            prev = content

    new_content = content[len(baseline) :] if len(content) > len(baseline) else ""
    return strip_ansi(new_content).strip()
