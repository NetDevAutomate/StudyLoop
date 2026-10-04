"""Integration tests for ``practice_check`` delivery over the two live transports.

Lane T of module-contract v1 (proposal §5.7, DoD item 5). The scenarios are the ones in
``openspec/changes/module-contract-v1/specs/session-transports/spec.md``; each test names
the scenario it proves. Marked ``integration``, so the default suite deselects them
(``addopts`` in ``pyproject.toml``); run with::

    env -u VIRTUAL_ENV uv run pytest packages/studyloop/tests/integration -m integration -q

Each test drives a REAL transport (``pty.fork()`` child / NDJSON JSON-RPC subprocess)
against a fake mentor that reports back exactly what reached it, and asserts the
behaviour ADR-0012 requires, through ``studyloop.session.module_delivery.deliver``.

Wave 0 wrote the first four tests against a seam -- today's raw
``transport.send_input(text.encode())`` (``web/routes/session/_ws.py:198-201``) --
so each was RED on its assertion (``evidence/T/integration-*.red.txt``). Wave 1
retired the seam once the module existed and added the three scenarios council M0
asked for, each red first against the transport as it then was.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from studyloop.session.active import ActiveSession
from studyloop.session.module_delivery import PracticeCheckEnvelope, deliver, render_envelope
from studyloop.session.transport import (
    AgentMessage,
    OutputBytes,
    SessionConfig,
    Stopped,
)
from studyloop.session.transports import acp as acp_module
from studyloop.session.transports.acp import ACPTransport
from studyloop.session.transports.pty import PTYTransport

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="PTY transport is POSIX-only"),
    # Same stdlib warning test_pty_transport.py scopes out: forkpty() from a
    # multi-threaded pytest process. Never suppressed globally.
    pytest.mark.filterwarnings(
        r"ignore:This process .* is multi-threaded, use of forkpty\(\) may lead to "
        r"deadlocks in the child\.:DeprecationWarning"
    ),
]

# --- ADR-0012 constants the tests assert against -----------------------------------

ENVELOPE_BOUND_BYTES = 8192  # Q3: whole rendered envelope, UTF-8
BEGIN_SENTINEL = "<<<studyloop:practice_check v1"
END_SENTINEL = "<<<end studyloop:practice_check>>>"
PASTE_BEGIN = b"\x1b[200~"  # Q1: DEC mode 2004 bracketed paste
PASTE_END = b"\x1b[201~"


def _sample_result(*, stdout: str, stderr: str = "") -> PracticeCheckEnvelope:
    """A failed `check` of kdrill's deployments/scale-to-three, triggered by the learner."""
    return PracticeCheckEnvelope(
        attempt_id="att-0001",
        module_id="kdrill",
        module_digest="sha256:0123456789abcdef0123456789abcdef",
        deck_id="deployments",
        task_id="scale-to-three",
        phase="check",
        exit_class="failed",
        exit_code=1,
        duration_s=2.5,
        triggered_by="learner",
        stdout_tail=stdout,
        stderr_tail=stderr,
    )


SEAM = "studyloop.session.module_delivery.deliver"


def _config(tmp_path: Path, agent: str) -> SessionConfig:
    return SessionConfig(
        study_session_id="module-delivery-it",
        agent=agent,
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
        cols=120,
        rows=40,
    )


# --- PTY: a fake mentor that reports the exact bytes it received ---------------------

_PTY_FAKE_MENTOR = textwrap.dedent(
    """
    import os, select, sys, time, tty
    fd = sys.stdin.fileno()
    tty.setraw(fd)                       # what every TUI harness agent does
    sys.stdout.write("\\x1b[?2004h")        # ... and enables bracketed paste (DEC 2004)
    sys.stdout.write("READY\\n"); sys.stdout.flush()
    buf = b""
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if ready:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\\x1b[201~\\r"):   # paste closed and submitted
                break
        elif buf:
            break                            # idle after input: whatever came is all
    sys.stdout.write("MENTOR-GOT " + buf.hex() + "\\n"); sys.stdout.flush()
    """
)


_PTY_FAKE_MENTOR_NO_2004 = textwrap.dedent(
    """
    import os, select, sys, time, tty
    fd = sys.stdin.fileno()
    tty.setraw(fd)                       # raw mode, but bracketed paste is never enabled
    sys.stdout.write("READY\\n"); sys.stdout.flush()
    buf = b""
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if ready:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
        elif buf:
            break                            # idle after input: whatever came is all
    sys.stdout.write("MENTOR-GOT " + buf.hex() + "\\n"); sys.stdout.flush()
    """
)


_PTY_FAKE_MENTOR_SLOW_READER = textwrap.dedent(
    """
    import os, select, sys, time, tty
    fd = sys.stdin.fileno()
    tty.setraw(fd)
    sys.stdout.write("\\x1b[?2004h")        # bracketed paste on
    sys.stdout.write("READY\\n"); sys.stdout.flush()
    buf = b""
    deadline = time.monotonic() + 20.0
    seen_end = False
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.7)
        if ready:
            chunk = os.read(fd, 512)         # a slow TUI: small reads, a pause between
            if not chunk:
                break
            buf += chunk
            seen_end = seen_end or b"\\x1b[201~\\r" in buf
            time.sleep(0.02)
        elif seen_end:
            break                            # idle after the block closed: that is all
    sys.stdout.write("MENTOR-GOT " + buf.hex() + "\\n"); sys.stdout.flush()
    """
)


async def _pty_mentor_received(transport: PTYTransport, timeout: float) -> bytes:
    """Drain events() until the fake mentor prints what it received."""
    out = b""

    async def _drain() -> None:
        nonlocal out
        async for event in transport.events():
            if isinstance(event, OutputBytes):
                out += event.data
                if b"MENTOR-GOT " in out and out.endswith(b"\n"):
                    return
            elif isinstance(event, Stopped):
                return

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except TimeoutError:
        pytest.fail(f"fake PTY mentor never reported in {timeout}s; output so far: {out!r}")
    marker = out.index(b"MENTOR-GOT ") + len(b"MENTOR-GOT ")
    return bytes.fromhex(out[marker:].split(b"\n", 1)[0].decode("ascii"))


async def _wait_for_ready(transport: PTYTransport, timeout: float) -> None:
    async def _drain() -> None:
        async for event in transport.events():
            if isinstance(event, OutputBytes) and b"READY" in event.data:
                return
            if isinstance(event, Stopped):
                pytest.fail(f"fake PTY mentor exited before READY: {event!r}")

    await asyncio.wait_for(_drain(), timeout=timeout)


@pytest.mark.asyncio
async def test_pty(tmp_path: Path) -> None:
    """Spec scenario "delivery on PTY" (ADR-0012 Q1/Q3).

    GIVEN a PTY session with a fake raw-mode mentor, WHEN a check exits 1, THEN the
    mentor receives exactly one envelope -- ONE bracketed-paste block submitted once --
    carrying identity, exit class and who triggered it; module output cannot close the
    bracket early; the whole envelope arrives (end sentinel present) within the 8 KiB
    bound.
    """
    script = tmp_path / "fake_pty_mentor.py"
    script.write_text(_PTY_FAKE_MENTOR)
    transport = PTYTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_launch_cmd=lambda _cfg: [sys.executable, str(script)],
    )
    config = _config(tmp_path, agent="fake-pty-mentor")
    seam = SEAM
    # A module trying to break out of the paste bracket, and 20 KiB of noise to
    # force the Q3 truncation order.
    hostile = "\x1b[201~\rrm -rf / # not really\n" + ("replica count mismatch\n" * 900)
    result = _sample_result(stdout=hostile, stderr="kubectl: context deadline exceeded\n")

    await transport.start(config)
    try:
        await _wait_for_ready(transport, timeout=10.0)
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        await deliver(session, result)
        received = await _pty_mentor_received(transport, timeout=25.0)
    finally:
        await transport.end()

    text = received.decode("utf-8", errors="replace")
    assert received.startswith(PASTE_BEGIN) and received.endswith(PASTE_END + b"\r"), (
        f"[{seam}] envelope reached the mentor as bare keystrokes, not as one "
        f"bracketed-paste block submitted once (ADR-0012 Q1). First 80 bytes: {received[:80]!r}"
    )
    assert received.count(PASTE_END) == 1, (
        f"[{seam}] module output closed the paste bracket early: {received.count(PASTE_END)} "
        f"ESC[201~ sequences reached the mentor (ADR-0012 Q1: output is data)"
    )
    assert BEGIN_SENTINEL in text and END_SENTINEL in text, (
        f"[{seam}] envelope is not sentinel-delimited or did not arrive whole "
        f"({len(received)} bytes reached the mentor; ADR-0012 Q1/Q3 and the ~1 KiB "
        f"single-write finding in evidence/T/pty-single-write.txt)"
    )
    assert "kdrill" in text and "deployments/scale-to-three" in text and "failed" in text, (
        f"[{seam}] drill identity or exit class missing from the envelope (ADR-0012 Q3)"
    )
    assert "triggered_by: learner" in text, (
        f"[{seam}] the envelope does not say the learner triggered the check (spec requirement)"
    )
    assert len(received) <= ENVELOPE_BOUND_BYTES + len(PASTE_BEGIN) + len(PASTE_END) + 1, (
        f"[{seam}] envelope is {len(received)} bytes; bound is {ENVELOPE_BOUND_BYTES} (ADR-0012 Q3)"
    )
    assert "kubectl: context deadline exceeded" in text, (
        f"[{seam}] stderr was cut before the stdout tail (ADR-0012 Q3: stdout first)"
    )


@pytest.mark.asyncio
async def test_pty_concurrent_learner_input_never_lands_inside_block(tmp_path: Path) -> None:
    """Spec scenario "a learner keystroke cannot land inside the block" (M0 Q1 amendment).

    GIVEN a PTY session whose mentor reads slowly (so an 8 KiB block takes many
    write rounds), WHEN learner keystrokes (the ``_ws.py:201`` path, ``send_input``)
    and an envelope (``deliver_block``) are sent concurrently, THEN the envelope's
    bytes are contiguous in the child's input -- exactly the rendered block -- and
    every learner byte precedes or follows the whole block, in order.
    """
    script = tmp_path / "fake_pty_mentor_slow.py"
    script.write_text(_PTY_FAKE_MENTOR_SLOW_READER)
    transport = PTYTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_launch_cmd=lambda _cfg: [sys.executable, str(script)],
    )
    config = _config(tmp_path, agent="fake-pty-mentor")
    seam = SEAM
    result = _sample_result(stdout="replica count mismatch\n" * 900, stderr="boom\n")
    keys = [f"k{i:02d}".encode("ascii") for i in range(40)]

    await transport.start(config)
    try:
        await _wait_for_ready(transport, timeout=10.0)
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )

        async def _learner_types() -> None:
            for key in keys:
                await transport.send_input(key)
                await asyncio.sleep(0.005)

        delivery = asyncio.create_task(deliver(session, result))
        typing = asyncio.create_task(_learner_types())
        outcome = await delivery
        await typing
        received = await _pty_mentor_received(transport, timeout=25.0)
    finally:
        await transport.end()

    expected = render_envelope(result, framing="pty")
    assert received.count(PASTE_BEGIN) == 1 and received.count(PASTE_END) == 1, (
        f"[{seam}] expected exactly one bracketed block in the child's input"
    )
    begin = received.index(PASTE_BEGIN)
    end = received.index(PASTE_END + b"\r") + len(PASTE_END) + 1
    block = received[begin:end]
    first_diff = next(
        (i for i, (a, b) in enumerate(zip(block, expected, strict=False)) if a != b),
        min(len(block), len(expected)),
    )
    assert block == expected, (
        f"[{seam}] learner bytes landed INSIDE the block: {len(block)} bytes arrived between "
        f"the paste brackets, {len(expected)} rendered; first difference at byte {first_diff} "
        f"(M0 Q1: one lock for every writer)"
    )
    outside = received[:begin] + received[end:]
    assert outside == b"".join(keys), (
        f"[{seam}] learner bytes were lost or reordered around the block: {outside!r}"
    )
    assert getattr(outcome, "status", None) == "delivered", f"[{seam}] {outcome!r}"


@pytest.mark.asyncio
async def test_pty_mode_2004_off_falls_back_to_one_line(tmp_path: Path) -> None:
    """Spec scenario "bracketed paste off falls back to one line" (M0 Q3).

    GIVEN a PTY session whose child never enabled DEC mode 2004, WHEN an envelope is
    delivered, THEN it arrives as exactly one printable line -- output newlines
    escaped as the two characters ``\\n``, sentinels kept, no ESC -- followed by one
    CR, and the outcome says ``delivered``. (Raw multi-line text + CR would submit
    each line as its own prompt and splinter the envelope.)
    """
    script = tmp_path / "fake_pty_mentor_no_2004.py"
    script.write_text(_PTY_FAKE_MENTOR_NO_2004)
    transport = PTYTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_launch_cmd=lambda _cfg: [sys.executable, str(script)],
    )
    config = _config(tmp_path, agent="fake-pty-mentor")
    seam = SEAM
    result = _sample_result(stdout="replica count mismatch\n" * 3, stderr="boom\n")

    await transport.start(config)
    try:
        await _wait_for_ready(transport, timeout=10.0)
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        outcome = await deliver(session, result)
        received = await _pty_mentor_received(transport, timeout=25.0)
    finally:
        await transport.end()

    text = received.decode("utf-8", errors="replace")
    assert received.endswith(b"\r") and received.count(b"\r") == 1, (
        f"[{seam}] not one line submitted once: {received[-40:]!r} (M0 Q3 fallback)"
    )
    assert b"\n" not in received and b"\x1b" not in received, (
        f"[{seam}] mode 2004 is off, yet raw newlines or ESC reached the mentor -- a line "
        f"editor would submit each line separately (M0 Q3). First 80 bytes: {received[:80]!r}"
    )
    assert text.startswith(BEGIN_SENTINEL) and END_SENTINEL in text, (
        f"[{seam}] sentinels missing from the one-line envelope: {text[:80]!r}"
    )
    assert "| replica count mismatch\\n| replica count mismatch" in text, (
        f"[{seam}] output newlines must be escaped as the two characters \\n"
    )
    assert "kdrill" in text and "deployments/scale-to-three" in text and "failed" in text
    assert getattr(outcome, "status", None) == "delivered", f"[{seam}] {outcome!r}"


# --- ACP: a fake mentor that echoes each prompt and notices overlapping ones ---------

_ACP_FAKE_MENTOR = textwrap.dedent(
    """
    import json, os, select, sys, time

    _buf = b""

    def read_frame(timeout):
        \"\"\"Unbuffered NDJSON reader: a frame already sitting in the pipe is seen.\"\"\"
        global _buf
        deadline = time.monotonic() + timeout
        while b"\\n" not in _buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([0], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(0, 65536)
            if not chunk:
                return None
            _buf += chunk
        line, _buf = _buf.split(b"\\n", 1)
        return json.loads(line)

    def emit(frame):
        sys.stdout.write(json.dumps(frame) + "\\n"); sys.stdout.flush()

    def update(session_id, record):
        emit({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": json.dumps(record)}}}})

    session_id = "fake-mentor-1"
    pending = []
    turn = 0
    while True:
        frame = pending.pop(0) if pending else read_frame(30.0)
        if frame is None:
            break
        method, rid = frame.get("method"), frame.get("id")
        if method == "initialize":
            emit({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": 1, "agentCapabilities": {}, "authMethods": [],
                "agentInfo": {"name": "Fake ACP Mentor", "version": "0"}}})
        elif method == "session/new":
            emit({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": session_id}})
        elif method == "session/prompt":
            turn += 1
            blocks = frame.get("params", {}).get("prompt", [])
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            overlapping = 0
            if turn == 1:
                # The learner's turn is "thinking" for a second. Any session/prompt
                # that arrives meanwhile overlaps it (ADR-0012 Q2).
                deadline = time.monotonic() + 1.0
                while True:
                    nxt = read_frame(max(0.0, deadline - time.monotonic()))
                    if nxt is None:
                        break
                    if nxt.get("method") == "session/prompt":
                        overlapping += 1
                    pending.append(nxt)
            update(session_id, {"turn": turn, "received": text, "overlapping_prompts": overlapping})
            emit({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "session/cancel":
            emit({"jsonrpc": "2.0", "id": rid, "result": None})
        elif rid is not None:
            emit({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32601, "message": "Method not found"}})
    """
)


_ACP_FAKE_MENTOR_HUNG = textwrap.dedent(
    """
    import json, os, select, sys, time

    _buf = b""

    def read_frame(timeout):
        global _buf
        deadline = time.monotonic() + timeout
        while b"\\n" not in _buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([0], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(0, 65536)
            if not chunk:
                return None
            _buf += chunk
        line, _buf = _buf.split(b"\\n", 1)
        return json.loads(line)

    def emit(frame):
        sys.stdout.write(json.dumps(frame) + "\\n"); sys.stdout.flush()

    def update(session_id, record):
        emit({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": json.dumps(record)}}}})

    def prompt_text(frame):
        blocks = frame.get("params", {}).get("prompt", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    session_id = "fake-mentor-hung"
    pending = []
    turn = 0
    while True:
        frame = pending.pop(0) if pending else read_frame(30.0)
        if frame is None:
            break
        method, rid = frame.get("method"), frame.get("id")
        if method == "initialize":
            emit({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": 1, "agentCapabilities": {}, "authMethods": [],
                "agentInfo": {"name": "Fake hung ACP mentor", "version": "0"}}})
        elif method == "session/new":
            emit({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": session_id}})
        elif method == "session/prompt" and turn == 0:
            # The first turn HANGS: no response until the client cancels it. Every
            # session/prompt that arrives meanwhile overlaps the hung turn (M0 Q5).
            turn += 1
            text = prompt_text(frame)
            overlapping = 0
            cancelled = False
            while True:
                nxt = read_frame(30.0)
                if nxt is None:
                    break
                if nxt.get("method") == "session/cancel":
                    emit({"jsonrpc": "2.0", "id": nxt.get("id"), "result": None})
                    time.sleep(0.5)              # a real agent takes a moment to unwind
                    cancelled = True
                    break
                if nxt.get("method") == "session/prompt":
                    overlapping += 1
                pending.append(nxt)
            update(session_id, {"turn": turn, "received": text,
                                "overlapping_prompts": overlapping, "cancelled": cancelled})
            emit({"jsonrpc": "2.0", "id": rid,
                  "result": {"stopReason": "cancelled" if cancelled else "end_turn"}})
        elif method == "session/prompt":
            turn += 1
            update(session_id, {"turn": turn, "received": prompt_text(frame),
                                "overlapping_prompts": 0, "cancelled": False})
            emit({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "session/cancel":
            emit({"jsonrpc": "2.0", "id": rid, "result": None})
        elif rid is not None:
            emit({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32601, "message": "Method not found"}})
    """
)


async def _acp_turn_records(transport: ACPTransport, *, turns: int, timeout: float) -> list[dict]:
    """Collect the fake mentor's per-turn records until ``turns`` turn_end events."""
    records: list[dict] = []
    ends = 0

    async def _drain() -> None:
        nonlocal ends
        async for event in transport.events():
            if isinstance(event, AgentMessage) and event.kind == "agent_chunk":
                content = event.payload.get("content") or {}
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    records.append(json.loads(content["text"]))
            elif isinstance(event, AgentMessage) and event.kind == "turn_end":
                ends += 1
                if ends >= turns:
                    return
            elif isinstance(event, Stopped):
                return

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except TimeoutError:
        pytest.fail(f"fake ACP mentor: {ends}/{turns} turn_end in {timeout}s; records={records!r}")
    return records


def _acp_transport(tmp_path: Path) -> ACPTransport:
    script = tmp_path / "fake_acp_mentor.py"
    script.write_text(_ACP_FAKE_MENTOR)
    return ACPTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_argv=lambda _cfg: [sys.executable, str(script)],
    )


@pytest.mark.asyncio
async def test_acp(tmp_path: Path) -> None:
    """Spec requirement "delivered on both the PTY and the ACP transports" (ADR-0012 Q1/Q3).

    With no learner turn in flight, the envelope arrives as one ``session/prompt``
    whose text is the same sentinel-delimited rendering as PTY -- without the ESC
    paste bracket (a prompt is already one turn) -- carrying identity and exit class
    within the bound.
    """
    transport = _acp_transport(tmp_path)
    config = _config(tmp_path, agent="kiro")
    seam = SEAM
    result = _sample_result(stdout="replica count mismatch\n" * 900, stderr="boom\n")

    await transport.start(config)
    try:
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        await deliver(session, result)
        records = await _acp_turn_records(transport, turns=1, timeout=15.0)
    finally:
        await transport.end()

    assert len(records) == 1, f"[{seam}] expected one prompt turn, got {records!r}"
    text = records[0]["received"]
    assert text.startswith(BEGIN_SENTINEL) and text.rstrip().endswith(END_SENTINEL), (
        f"[{seam}] ACP prompt is not a sentinel-labelled envelope (ADR-0012 Q1). "
        f"First 80 chars: {text[:80]!r}"
    )
    assert "\x1b" not in text, f"[{seam}] ESC bytes in an ACP prompt (bracket is PTY-only)"
    assert "kdrill" in text and "deployments/scale-to-three" in text and "failed" in text, (
        f"[{seam}] drill identity or exit class missing from the envelope (ADR-0012 Q3)"
    )
    assert len(text.encode("utf-8")) <= ENVELOPE_BOUND_BYTES, (
        f"[{seam}] envelope is {len(text.encode('utf-8'))} bytes; bound is "
        f"{ENVELOPE_BOUND_BYTES} (ADR-0012 Q3)"
    )
    assert "boom" in text, f"[{seam}] stderr cut before the stdout tail (ADR-0012 Q3)"


@pytest.mark.asyncio
async def test_acp_no_overlap_with_learner_turn(tmp_path: Path) -> None:
    """Spec scenario "delivery on ACP does not interleave with a learner turn" (ADR-0012 Q2).

    A practice_check prompt queues BEHIND the learner's in-flight turn and is delivered
    after it, never inside it.

    The learner's prompt goes first (exactly as ``_ws.py:201`` sends it); the fake
    mentor holds that turn open for a second and counts any session/prompt that
    arrives meanwhile. Today ``ACPTransport.send_input`` fires every prompt as an
    independent background task (acp.py:283-288), so the envelope overlaps.
    """
    transport = _acp_transport(tmp_path)
    config = _config(tmp_path, agent="kiro")
    seam = SEAM
    result = _sample_result(stdout="ok\n")

    await transport.start(config)
    try:
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        await transport.send_input(b"why did my rollout stall?")  # the learner's turn
        await deliver(session, result)  # the check completes while the mentor is thinking
        records = await _acp_turn_records(transport, turns=2, timeout=15.0)
    finally:
        await transport.end()

    by_turn = {r["turn"]: r for r in records}
    assert 1 in by_turn and 2 in by_turn, f"[{seam}] expected two turns, got {records!r}"
    assert by_turn[1]["received"] == "why did my rollout stall?", (
        f"[{seam}] the learner's prompt did not arrive first and intact: {by_turn[1]!r}"
    )
    assert by_turn[1]["overlapping_prompts"] == 0, (
        f"[{seam}] the practice_check prompt was written while the learner's turn was "
        f"still in flight ({by_turn[1]['overlapping_prompts']} overlapping session/prompt). "
        f"ADR-0012 Q2: queue behind the in-flight turn"
    )
    assert BEGIN_SENTINEL in by_turn[2]["received"], (
        f"[{seam}] second turn is not the labelled envelope: {by_turn[2]['received'][:80]!r}"
    )


@pytest.mark.asyncio
async def test_acp_hung_turn_times_out_once_and_does_not_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec scenario "a hung ACP turn times out once" (M0 Q5).

    GIVEN an ACP session whose fake agent never answers ``session/prompt`` until it
    is cancelled, WHEN an envelope is delivered, THEN after the bound the outcome is
    ``timed_out``, exactly one envelope was ever sent (never retried), the turn was
    cancelled, and a learner prompt fired while the cancellation was still
    unconfirmed does NOT overlap the cancelled turn -- the prompt lock is held until
    the agent has answered the cancelled prompt.

    The bound is 120 s in production (``acp.DELIVERY_TIMEOUT_S``); the test lowers
    it to 1 s because the suite's per-test ceiling is 60 s. The fake takes 0.5 s to
    confirm the cancel, and the learner types at 1.3 s -- inside that window.
    """
    # raising=False so the red before T4 (no constant, no deliver_block) fails on the
    # assertion below, not here; a renamed constant later would run 120 s into the
    # 60 s ceiling and fail just as loudly.
    monkeypatch.setattr(acp_module, "DELIVERY_TIMEOUT_S", 1.0, raising=False)
    script = tmp_path / "fake_acp_mentor_hung.py"
    script.write_text(_ACP_FAKE_MENTOR_HUNG)
    transport = ACPTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_argv=lambda _cfg: [sys.executable, str(script)],
    )
    config = _config(tmp_path, agent="kiro")
    seam = SEAM
    result = _sample_result(stdout="ok\n")

    await transport.start(config)
    try:
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        started = asyncio.get_running_loop().time()
        delivery = asyncio.create_task(deliver(session, result))
        await asyncio.sleep(1.3)  # past the bound; the cancel is in flight, unconfirmed
        await transport.send_input(b"are you there?")  # the learner, as _ws.py:201 sends it
        outcome = await delivery
        elapsed = asyncio.get_running_loop().time() - started
        records = await _acp_turn_records(transport, turns=2, timeout=15.0)
    finally:
        await transport.end()

    assert getattr(outcome, "status", None) == "timed_out", (
        f"[{seam}] a prompt the agent never answers must be reported timed_out: {outcome!r}"
    )
    assert "att-0001" in str(getattr(outcome, "reason", "")), f"[{seam}] {outcome!r}"
    assert elapsed >= 1.0, f"[{seam}] delivery returned before the bound: {elapsed:.2f}s"
    envelopes = [r for r in records if BEGIN_SENTINEL in r["received"]]
    assert len(envelopes) == 1, (
        f"[{seam}] exactly one envelope must be sent, never retried: {len(envelopes)} seen"
    )
    by_turn = {r["turn"]: r for r in records}
    assert 1 in by_turn and 2 in by_turn, f"[{seam}] expected two turns, got {records!r}"
    assert by_turn[1]["cancelled"] is True, (
        f"[{seam}] the hung turn was never cancelled (M0 Q5: cancel, hold, report)"
    )
    assert by_turn[1]["overlapping_prompts"] == 0, (
        f"[{seam}] the learner's prompt reached the agent while the timed-out turn was "
        f"still unconfirmed ({by_turn[1]['overlapping_prompts']} overlapping). M0 Q5: the "
        f"prompt lock is held until cancellation is confirmed"
    )
    assert by_turn[2]["received"] == "are you there?", f"[{seam}] {by_turn[2]!r}"


# --- Failure visibility: a closed transport ------------------------------------------


@pytest.mark.asyncio
async def test_pty_closed_transport_is_reported(tmp_path: Path) -> None:
    """Spec scenario "a closed transport is reported" (ADR-0012 Q4), on a real PTY.

    GIVEN a session whose mentor child has already exited, WHEN a check completes,
    THEN delivery returns an outcome that names the undelivered result and the reason
    -- instead of ``PTYTransport.send_input``'s silent return on EIO (pty.py:357-360).
    """
    script = tmp_path / "exits_at_once.py"
    script.write_text("import sys; sys.stdout.write('BYE\\n'); sys.stdout.flush(); sys.exit(0)\n")
    transport = PTYTransport(
        resolve_binary=lambda _agent: sys.executable,
        build_launch_cmd=lambda _cfg: [sys.executable, str(script)],
    )
    config = _config(tmp_path, agent="fake-pty-mentor")
    seam = SEAM
    result = _sample_result(stdout="ok\n")

    await transport.start(config)
    try:

        async def _until_stopped() -> None:
            async for event in transport.events():
                if isinstance(event, Stopped):
                    return

        await asyncio.wait_for(_until_stopped(), timeout=10.0)
        assert transport.is_running() is False, "precondition: the mentor child has exited"
        session = ActiveSession(
            study_session_id=config.study_session_id, transport=transport, config=config
        )
        outcome = await deliver(session, result)
    finally:
        await transport.end()

    assert outcome is not None, (
        f"[{seam}] delivery into a closed transport returned nothing: the drop is silent "
        f"(spec: 'a closed transport is reported'; ADR-0012 Q4)"
    )
    assert getattr(outcome, "status", None) == "transport_closed", (
        f"[{seam}] outcome did not name the reason: {outcome!r}"
    )
    message = str(getattr(outcome, "reason", ""))
    assert result.attempt_id in message or "deployments/scale-to-three" in message, (
        f"[{seam}] outcome does not name the undelivered result: {message!r}"
    )
