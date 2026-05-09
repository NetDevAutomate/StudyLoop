"""Tests for live agent session runtime transports."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from studyctl.session_runtime import AgentSessionManager, PtyAgentSessionTransport, SessionStartSpec
from studyctl.session_runtime.manager import _acp_command
from studyctl.session_runtime.pty import _merged_env, clean_terminal_output

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_pty_transport_streams_output_and_accepts_input(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "print('ready', flush=True)\n"
        "for line in sys.stdin:\n"
        "    print('echo:' + line.strip(), flush=True)\n"
    )
    spec = SessionStartSpec(
        session_id="test-session",
        topic="Python",
        energy=5,
        agent="python",
        command=[sys.executable, "-u", "-c", script],
        cwd=tmp_path,
    )
    transport = PtyAgentSessionTransport(spec)
    await transport.start()

    events = transport.events()
    first = await anext(events)
    assert first.type == "started"

    ready = await anext(events)
    assert ready.type == "output"
    assert "ready" in ready.data["text"]

    await transport.send("hello")
    chunks: list[str] = []
    for _ in range(5):
        event = await anext(events)
        if event.type == "output":
            chunks.append(str(event.data["text"]))
        if "echo:hello" in "".join(chunks):
            break

    await transport.stop()
    assert "echo:hello" in "".join(chunks)


def test_acp_command_supports_kiro_and_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    assert _acp_command("kiro") == ["/usr/bin/kiro-cli", "acp"]
    assert _acp_command("gemini") == ["/usr/bin/gemini", "--acp"]


def test_clean_terminal_output_strips_ansi_and_control_codes() -> None:
    raw = "\x1b[1D\x1b[4B\x1b[2K\x1b[1mClaude\x1b[0m\r\n\x07Ready"

    assert clean_terminal_output(raw) == "Claude\nReady"


def test_pty_env_uses_real_terminal_for_codex() -> None:
    assert _merged_env({"STUDYLOOP_AGENT": "codex"})["TERM"] == "xterm-256color"


def test_pty_env_keeps_claude_in_plain_text_mode() -> None:
    assert _merged_env({"STUDYLOOP_AGENT": "claude"})["TERM"] == "dumb"


@pytest.mark.asyncio
async def test_manager_falls_back_to_shell_when_no_agent_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("studyctl.session_runtime.manager._default_agent", lambda: "shell")
    manager = AgentSessionManager(base_dir=tmp_path)

    session_id, events = await manager.start_session(topic="Body Double", energy=4)
    started = await anext(events)

    await manager.stop(session_id)
    assert started.type == "started"
    assert started.data["agent"] == "shell"
