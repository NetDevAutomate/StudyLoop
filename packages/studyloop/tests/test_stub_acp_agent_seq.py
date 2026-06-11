"""Unit tests for STUB_ACP_PROMPT_UPDATES_SEQ in _stub_acp_agent.py.

These tests spawn the stub as a real subprocess, send NDJSON ``session/prompt``
requests over stdin, and assert the notification sequences emitted on stdout
match the per-turn scripted behaviour.

No Playwright, no browser, no web server — pure subprocess I/O.

Scenarios:
1. Happy-path SEQ: two prompts emit different chunk text.
2. Back-compat: legacy STUB_ACP_PROMPT_UPDATES sends the same sequence every turn.
3. Edge-case repeat: SEQ has 2 entries; third prompt repeats the last.
4. Both set: _SEQ wins over STUB_ACP_PROMPT_UPDATES.
5. Neither set: stub still works (no notifications, result still sent).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_STUB = Path(__file__).parent / "_stub_acp_agent.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk_notif(text: str) -> dict[str, Any]:
    """Build a minimal session/update notification carrying *text*."""
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "stub-session-1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


def _make_request(method: str, req_id: int, params: dict[str, Any] | None = None) -> str:
    frame: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        frame["params"] = params
    return json.dumps(frame) + "\n"


def _run_stub(
    requests: list[str],
    extra_env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Spawn the stub, feed it *requests* via stdin, return all stdout frames.

    The stub exits when stdin closes (no more lines), so we simply write
    everything then close the pipe.
    """
    import os

    env = {**os.environ}
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        [sys.executable, str(_STUB)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    payload = "".join(requests).encode()
    stdout_bytes, stderr_bytes = proc.communicate(input=payload, timeout=10)
    if proc.returncode not in (0, None):
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        pytest.fail(
            f"Stub exited {proc.returncode}. stderr:\n{stderr_text}\n"
            f"stdout:\n{stdout_bytes.decode('utf-8', errors='replace')}"
        )
    frames = []
    for line in stdout_bytes.splitlines():
        line = line.strip()
        if line:
            frames.append(json.loads(line))
    return frames


def _do_handshake(requests: list[str]) -> None:
    """Prepend initialize + session/new requests for a minimal handshake."""
    requests.insert(0, _make_request("session/new", 2, {"sessionId": "stub-session-1"}))
    requests.insert(0, _make_request("initialize", 1, {"protocolVersion": 1}))


def _extract_notif_texts(frames: list[dict[str, Any]]) -> list[str]:
    """Pull out chunk texts from session/update notification frames."""
    texts = []
    for f in frames:
        if f.get("method") == "session/update":
            content = f.get("params", {}).get("update", {}).get("content", {})
            if isinstance(content, dict) and "text" in content:
                texts.append(content["text"])
    return texts


def _get_prompt_results(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the result frames that match prompt responses (have stopReason)."""
    return [
        f
        for f in frames
        if "result" in f and isinstance(f.get("result"), dict) and "stopReason" in f["result"]
    ]


# ---------------------------------------------------------------------------
# Test 1: Happy-path SEQ — two prompts emit different chunk text
# ---------------------------------------------------------------------------


class TestSeqHappyPath:
    def test_two_prompts_emit_different_chunks(self) -> None:
        """STUB_ACP_PROMPT_UPDATES_SEQ drives per-turn different text."""
        seq = [
            [_make_chunk_notif("turn-one-text")],
            [_make_chunk_notif("turn-two-text")],
        ]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={"STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(seq)},
        )
        texts = _extract_notif_texts(frames)
        assert texts == ["turn-one-text", "turn-two-text"], (
            f"Expected [turn-one-text, turn-two-text], got {texts!r}"
        )

    def test_seq_prompt_results_have_end_turn(self) -> None:
        """Each SEQ-driven prompt also emits a stopReason result."""
        seq = [
            [_make_chunk_notif("a")],
            [_make_chunk_notif("b")],
        ]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={"STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(seq)},
        )
        results = _get_prompt_results(frames)
        assert len(results) == 2
        assert all(r["result"]["stopReason"] == "end_turn" for r in results)


# ---------------------------------------------------------------------------
# Test 2: Back-compat — legacy STUB_ACP_PROMPT_UPDATES, same sequence every turn
# ---------------------------------------------------------------------------


class TestBackCompat:
    def test_flat_updates_applied_to_every_turn(self) -> None:
        """Without _SEQ, STUB_ACP_PROMPT_UPDATES repeats for each prompt."""
        flat = [_make_chunk_notif("always-this")]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
            _make_request("session/prompt", 5, {"sessionId": "stub-session-1", "prompt": "q3"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={"STUB_ACP_PROMPT_UPDATES": json.dumps(flat)},
        )
        texts = _extract_notif_texts(frames)
        assert texts == ["always-this", "always-this", "always-this"], (
            f"Back-compat: expected same text 3x, got {texts!r}"
        )


# ---------------------------------------------------------------------------
# Test 3: Edge-case repeat — SEQ exhausted, last entry repeats
# ---------------------------------------------------------------------------


class TestSeqRepeat:
    def test_third_prompt_repeats_last_seq_entry(self) -> None:
        """When prompts > SEQ length, the last entry repeats."""
        seq = [
            [_make_chunk_notif("first")],
            [_make_chunk_notif("second")],
        ]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
            _make_request("session/prompt", 5, {"sessionId": "stub-session-1", "prompt": "q3"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={"STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(seq)},
        )
        texts = _extract_notif_texts(frames)
        # Turn 0 → "first", turn 1 → "second", turn 2 → "second" (repeat)
        assert texts == ["first", "second", "second"], (
            f"Expected last-entry repeat on 3rd prompt, got {texts!r}"
        )


# ---------------------------------------------------------------------------
# Test 4: Both set — _SEQ wins over STUB_ACP_PROMPT_UPDATES
# ---------------------------------------------------------------------------


class TestSeqWinsOverFlat:
    def test_seq_takes_priority_when_both_set(self) -> None:
        """_SEQ env var takes priority; STUB_ACP_PROMPT_UPDATES is ignored."""
        seq = [
            [_make_chunk_notif("seq-wins")],
        ]
        flat = [_make_chunk_notif("flat-loses")]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={
                "STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(seq),
                "STUB_ACP_PROMPT_UPDATES": json.dumps(flat),
            },
        )
        texts = _extract_notif_texts(frames)
        assert texts == ["seq-wins"], f"Expected _SEQ to win, got {texts!r}"

    def test_seq_wins_across_multiple_turns(self) -> None:
        """_SEQ wins even for a second turn when both vars are set."""
        seq = [
            [_make_chunk_notif("seq-a")],
            [_make_chunk_notif("seq-b")],
        ]
        flat = [_make_chunk_notif("flat-should-not-appear")]
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(
            reqs,
            extra_env={
                "STUB_ACP_PROMPT_UPDATES_SEQ": json.dumps(seq),
                "STUB_ACP_PROMPT_UPDATES": json.dumps(flat),
            },
        )
        texts = _extract_notif_texts(frames)
        assert texts == ["seq-a", "seq-b"], f"Expected seq-a, seq-b (not flat), got {texts!r}"


# ---------------------------------------------------------------------------
# Test 5: Neither set — stub still works (no notifications, result still sent)
# ---------------------------------------------------------------------------


class TestNeitherSet:
    def test_no_notifications_emitted_no_crash(self) -> None:
        """With no env vars set, stub sends zero notifications but valid results."""
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(reqs, extra_env={})

        texts = _extract_notif_texts(frames)
        assert texts == [], f"Expected no notifications, got {texts!r}"

        results = _get_prompt_results(frames)
        assert len(results) == 1
        assert results[0]["result"]["stopReason"] == "end_turn"

    def test_no_notifications_multiple_turns_no_crash(self) -> None:
        """Multiple prompts with no env vars set — still no crash, correct results."""
        reqs: list[str] = [
            _make_request("session/prompt", 3, {"sessionId": "stub-session-1", "prompt": "q1"}),
            _make_request("session/prompt", 4, {"sessionId": "stub-session-1", "prompt": "q2"}),
        ]
        _do_handshake(reqs)

        frames = _run_stub(reqs, extra_env={})

        texts = _extract_notif_texts(frames)
        assert texts == []

        results = _get_prompt_results(frames)
        assert len(results) == 2
