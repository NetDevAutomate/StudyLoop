"""Tests for tmux pane capture and ANSI stripping utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from studyctl.eval.capture import (
    capture_pane_plain,
    capture_response,
    send_keys,
    strip_ansi,
)

# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------


def test_strip_ansi_removes_color_codes() -> None:
    assert strip_ansi("\x1b[32mgreen\x1b[0m") == "green"


def test_strip_ansi_removes_cursor_codes() -> None:
    assert strip_ansi("\x1b[2J\x1b[H") == ""


def test_strip_ansi_preserves_plain_text() -> None:
    assert strip_ansi("hello world") == "hello world"


def test_strip_ansi_handles_empty_string() -> None:
    assert strip_ansi("") == ""


# ---------------------------------------------------------------------------
# capture_pane_plain
# ---------------------------------------------------------------------------


def test_capture_pane_plain_calls_tmux() -> None:
    mock_result = MagicMock(returncode=0, stdout="")
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        capture_pane_plain("test-session")
        mock_run.assert_called_once_with(
            ["tmux", "capture-pane", "-t", "test-session", "-p", "-S", "-"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_capture_pane_plain_returns_stdout() -> None:
    mock_result = MagicMock(returncode=0, stdout="Hello\n")
    with patch("subprocess.run", return_value=mock_result):
        result = capture_pane_plain("test-session")
    assert result == "Hello\n"


def test_capture_pane_plain_returns_empty_on_failure() -> None:
    mock_result = MagicMock(returncode=1, stdout="some output")
    with patch("subprocess.run", return_value=mock_result):
        result = capture_pane_plain("test-session")
    assert result == ""


# ---------------------------------------------------------------------------
# send_keys
# ---------------------------------------------------------------------------


def test_send_keys_calls_tmux() -> None:
    mock_result = MagicMock(returncode=0, stdout="")
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        send_keys("my-session", "What is recursion?")
        mock_run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "my-session", "What is recursion?", "Enter"],
            capture_output=True,
            check=False,
        )


# ---------------------------------------------------------------------------
# Helpers for capture_response tests
# ---------------------------------------------------------------------------


def _mock_run_sequence(outputs: list[str]):
    """Returns a side_effect function that returns different tmux output per call."""
    call_count = [0]

    def side_effect(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if "capture-pane" in cmd:
            idx = min(call_count[0], len(outputs) - 1)
            call_count[0] += 1
            return MagicMock(returncode=0, stdout=outputs[idx])
        # send-keys returns nothing interesting
        return MagicMock(returncode=0, stdout="")

    return side_effect


# ---------------------------------------------------------------------------
# capture_response
# ---------------------------------------------------------------------------


def test_capture_response_extracts_new_content() -> None:
    # baseline = "Before\n", then response appears
    outputs = [
        "Before\n",
        "Before\nResponse text\n",
        "Before\nResponse text\n",
        "Before\nResponse text\n",
        "Before\nResponse text\n",
        "Before\nResponse text\n",
        "Before\nResponse text\n",
    ]
    with patch("subprocess.run", side_effect=_mock_run_sequence(outputs)), patch("time.sleep"):
        result = capture_response("sess", "Ask something", timeout=90, stable_seconds=5)
    assert result == "Response text"


def test_capture_response_returns_empty_on_no_change() -> None:
    # Same content every call — no new content after baseline
    outputs = ["SameContent\n"]
    with patch("subprocess.run", side_effect=_mock_run_sequence(outputs)), patch("time.sleep"):
        result = capture_response("sess", "Ask something", timeout=90, stable_seconds=5)
    assert result == ""


def test_capture_response_strips_ansi_from_result() -> None:
    ansi_response = "Before\n\x1b[32mcolored answer\x1b[0m\n"
    outputs = [
        "Before\n",
        ansi_response,
        ansi_response,
        ansi_response,
        ansi_response,
        ansi_response,
        ansi_response,
    ]
    with patch("subprocess.run", side_effect=_mock_run_sequence(outputs)), patch("time.sleep"):
        result = capture_response("sess", "Question", timeout=90, stable_seconds=5)
    assert result == "colored answer"


def test_capture_response_waits_for_stability() -> None:
    # Content changes for 3 calls, then stable for stable_seconds=3
    outputs = [
        "Before\n",  # baseline
        "Before\nChunk1\n",  # call 1 — changed
        "Before\nChunk2\n",  # call 2 — changed
        "Before\nFinal\n",  # call 3 — changed
        "Before\nFinal\n",  # call 4 — stable 1
        "Before\nFinal\n",  # call 5 — stable 2
        "Before\nFinal\n",  # call 6 — stable 3 → break
    ]
    sleep_mock = MagicMock()
    with (
        patch("subprocess.run", side_effect=_mock_run_sequence(outputs)),
        patch("time.sleep", sleep_mock),
    ):
        result = capture_response("sess", "Question", timeout=90, stable_seconds=3)

    # sleep called once per loop iteration: 3 changing + 3 stable = 6 times
    assert sleep_mock.call_count == 6
    assert result == "Final"
