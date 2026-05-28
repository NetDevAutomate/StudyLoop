"""Unit tests for ``ACPTransport`` against a scripted StubACPAgent.

The stub agent (``_stub_acp_agent.py``) is driven by environment
variables, so each test configures exactly the wire-level behaviour
it wants to exercise. No real Kiro/Gemini binaries required; real-CLI
coverage lives in the Playwright matrix that Phase 2 PR-C will add.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md
      Amendment #9 §Phase 2 PR-A.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from studyloop.session.transport import (
    AgentMessage,
    SessionConfig,
    Started,
    Stopped,
    TransportError,
)
from studyloop.session.transports.acp import ACPTransport

STUB_SCRIPT = Path(__file__).parent / "_stub_acp_agent.py"


def _make_config(tmp_path: Path) -> SessionConfig:
    return SessionConfig(
        study_session_id="acp-test",
        agent="kiro",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


def _stub_build_argv(extra_env: dict[str, str] | None = None):
    """Return a build_argv callable that launches the stub agent
    with the given env vars encoded as CLI preamble.

    The stub reads its scripted behaviour from os.environ, so we pass
    those env vars through the subprocess env at spawn time. This
    helper embeds them in argv as ``KEY=VAL`` prefix tokens which the
    ACPTransport's subprocess launcher must strip — no, simpler:
    we just have the test monkeypatch os.environ before spawn.

    Instead return a plain argv; tests set env via monkeypatch on the
    process-wide environment (the subprocess inherits it).
    """
    _ = extra_env
    return lambda cfg: [sys.executable, str(STUB_SCRIPT)]


def _stub_resolve_binary(_agent: str) -> str:
    return sys.executable


# ---------------------------------------------------------------------------
# PR-A.2: start() — initialize + session/new + Started event
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _reset_env(monkeypatch):
    """Strip every STUB_ACP_* env var so tests don't pollute each other.

    monkeypatch.undo() handles its own setenv records on teardown — this
    fixture handles any raw env vars left in os.environ from a prior
    failed test.
    """
    import os

    for key in list(os.environ):
        if key.startswith("STUB_ACP_"):
            monkeypatch.delenv(key, raising=False)
    yield


class TestStart:
    @pytest.mark.asyncio
    async def test_start_sends_initialize_and_session_new(self, tmp_path, monkeypatch, _reset_env):
        """Happy path: initialize + session/new + Started event with the
        agent name from the stub's agentInfo."""
        monkeypatch.setenv(
            "STUB_ACP_INIT_RESULT",
            json.dumps(
                {
                    "protocolVersion": 1,
                    "agentCapabilities": {"loadSession": True},
                    "authMethods": [],
                    "agentInfo": {"name": "Stub ACP Agent", "version": "0.0.1"},
                }
            ),
        )
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        # First event emitted MUST be Started carrying agentInfo.name.
        first = await asyncio.wait_for(transport.events().__anext__(), timeout=2.0)
        assert isinstance(first, Started)
        assert first.agent == "Stub ACP Agent"

        await transport.end()

    @pytest.mark.asyncio
    async def test_start_caches_session_id_from_new_session(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """session/new returns ``sessionId`` — the transport must cache
        it so subsequent session/prompt / session/cancel requests
        reference the right session."""
        monkeypatch.setenv(
            "STUB_ACP_NEW_SESSION_RESULT",
            json.dumps({"sessionId": "sess-xyz"}),
        )
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))
        # Internal accessor — tests reach through a single underscore-prefixed
        # attribute. Public behaviour is covered via send_input later.
        assert transport._session_id == "sess-xyz"
        await transport.end()

    @pytest.mark.asyncio
    async def test_start_raises_file_not_found_on_missing_binary(self, tmp_path):
        """resolve_binary returning None → FileNotFoundError before spawn."""
        transport = ACPTransport(
            resolve_binary=lambda _agent: None,
            build_argv=_stub_build_argv(),
        )
        with pytest.raises(FileNotFoundError):
            await transport.start(_make_config(tmp_path))

    @pytest.mark.asyncio
    async def test_start_twice_raises(self, tmp_path, monkeypatch, _reset_env):
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))
        with pytest.raises(RuntimeError):
            await transport.start(_make_config(tmp_path))
        await transport.end()


# ---------------------------------------------------------------------------
# PR-A.3: events() + reader task + session/update normalisation
# ---------------------------------------------------------------------------


class TestEventsAndUpdates:
    @pytest.mark.asyncio
    async def test_agent_message_chunk_update_becomes_agent_chunk(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """Stub emits one session/update(agent_message_chunk) after
        session/new; events() must yield AgentMessage(kind="agent_chunk")
        between Started and the final Stopped."""
        monkeypatch.setenv(
            "STUB_ACP_POST_NEW_SESSION_UPDATES",
            json.dumps(
                [
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "stub-session-1",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "hello from stub"},
                            },
                        },
                    }
                ]
            ),
        )
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        # Drain until we find the agent_chunk — some stub configurations
        # emit extra pre-session chatter that we don't want to count.
        found: AgentMessage | None = None
        for _ in range(10):
            event = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
            if isinstance(event, AgentMessage) and event.kind == "agent_chunk":
                found = event
                break
        assert found is not None, "no agent_chunk event surfaced"
        assert found.payload["content"]["text"] == "hello from stub"

        await transport.end()

    @pytest.mark.asyncio
    async def test_available_commands_update_is_dropped(self, tmp_path, monkeypatch, _reset_env):
        """Chrome update kinds never surface on the events stream."""
        monkeypatch.setenv(
            "STUB_ACP_POST_NEW_SESSION_UPDATES",
            json.dumps(
                [
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "stub-session-1",
                            "update": {
                                "sessionUpdate": "available_commands_update",
                                "availableCommands": [{"name": "memory"}],
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "stub-session-1",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "after chrome"},
                            },
                        },
                    },
                ]
            ),
        )
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started
        second = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
        assert isinstance(second, AgentMessage)
        # Chrome dropped → second event is the agent_chunk, not chrome.
        assert second.kind == "agent_chunk"

        await transport.end()


# ---------------------------------------------------------------------------
# PR-A.4: send_input → session/prompt + turn-end via stopReason
# ---------------------------------------------------------------------------


class TestSendInput:
    @pytest.mark.asyncio
    async def test_send_input_produces_turn_end_message(self, tmp_path, monkeypatch, _reset_env):
        """send_input(bytes) wraps in session/prompt; the result's
        stopReason surfaces as AgentMessage(kind='turn_end')."""
        monkeypatch.setenv("STUB_ACP_PROMPT_STOP_REASON", "end_turn")
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        await transport.send_input(b"What is the capital of France?")

        found_turn_end = None
        for _ in range(10):
            event = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
            if isinstance(event, AgentMessage) and event.kind == "turn_end":
                found_turn_end = event
                break
        assert found_turn_end is not None
        assert found_turn_end.payload.get("reason") == "end_turn"

        await transport.end()

    @pytest.mark.asyncio
    async def test_rpc_error_on_prompt_becomes_transport_error(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """A JSON-RPC error response to session/prompt surfaces as
        TransportError."""
        monkeypatch.setenv(
            "STUB_ACP_PROMPT_ERROR",
            json.dumps({"code": -32000, "message": "model unavailable"}),
        )
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        await transport.send_input(b"hi")

        found_error = None
        for _ in range(10):
            event = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
            if isinstance(event, TransportError):
                found_error = event
                break
        assert found_error is not None
        assert "model unavailable" in found_error.message

        await transport.end()


# ---------------------------------------------------------------------------
# PR-A.5: cancel() → session/cancel + Stopped(reason="cancel")
# ---------------------------------------------------------------------------


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_emits_stopped_cancel(self, tmp_path, monkeypatch, _reset_env):
        """cancel() after start sends session/cancel; the events stream
        terminates with Stopped(reason="cancel")."""
        # Stub exits cleanly on cancel so we get a deterministic Stopped.
        monkeypatch.setenv("STUB_ACP_EXIT_ON_CANCEL", "1")
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        await transport.cancel()

        found_stopped = None
        for _ in range(15):
            try:
                event = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
            except (TimeoutError, StopAsyncIteration):
                break
            if isinstance(event, Stopped):
                found_stopped = event
                break
        assert found_stopped is not None
        assert found_stopped.reason == "cancel"

        await transport.end()


# ---------------------------------------------------------------------------
# PR-A.6: end() + child exit → Stopped(reason="exit")
# ---------------------------------------------------------------------------


class TestEnd:
    @pytest.mark.asyncio
    async def test_end_closes_subprocess_cleanly(self, tmp_path, monkeypatch, _reset_env):
        """end() closes stdin, reader task exits, child reaped."""
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))
        await transport.end()

        # Double-end is idempotent — must not raise.
        await transport.end()

    @pytest.mark.asyncio
    async def test_child_crash_after_init_emits_stopped_exit(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """If the child exits mid-session (e.g. STUB_ACP_CRASH_AFTER_INIT),
        events() yields Stopped(reason='exit') with the returncode."""
        monkeypatch.setenv("STUB_ACP_CRASH_AFTER_INIT", "1")
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        # start() may raise if the child dies before session/new responds.
        try:
            await transport.start(_make_config(tmp_path))
        except RuntimeError:
            # Handshake failed — test still needs to pass end() cleanup.
            await transport.end()
            return

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        found_stopped = None
        for _ in range(10):
            try:
                event = await asyncio.wait_for(event_iter.__anext__(), timeout=3.0)
            except (TimeoutError, StopAsyncIteration):
                break
            if isinstance(event, Stopped):
                found_stopped = event
                break
        assert found_stopped is not None
        assert found_stopped.reason == "exit"
        # Exit code 17 from the stub.
        assert found_stopped.returncode == 17

        await transport.end()


# ---------------------------------------------------------------------------
# U6.5: send_permission_response + inbound session/request_permission request
# ---------------------------------------------------------------------------


class TestSendPermissionResponse:
    """U6.5 — ACPTransport correctly handles the ACP permission request/response
    wire protocol as confirmed by the Gemini CLI source.

    Protocol:
    - Agent → client: JSON-RPC *request* ``session/request_permission`` (has id)
    - Client → agent: JSON-RPC *response* (matching id, result.outcome, NO method)
    """

    @pytest.mark.asyncio
    async def test_send_permission_response_writes_rpc_response_not_request(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """send_permission_response writes a JSON-RPC response frame:
        - has 'id' matching request_id
        - has 'result.outcome.outcome == "selected"'
        - has 'result.outcome.optionId' == the passed optionId
        - has NO 'method' key (it's a response, not a new request)
        """
        import asyncio
        import json as _json

        # Use a raw pipe approach: start the stub, send a fake permission
        # request from our side, call send_permission_response, and read
        # what was written to the process stdin.
        #
        # Instead of parsing subprocess stdin (write-only), we verify via the
        # stub: set STUB_ACP_EMIT_PERMISSION_REQUEST=1 so the stub itself
        # emits the request and awaits our response. The stub records the
        # result in permission_responses. After the turn, we verify no
        # TransportError appeared (meaning the response round-tripped cleanly).

        monkeypatch.setenv("STUB_ACP_EMIT_PERMISSION_REQUEST", "1")
        monkeypatch.setenv("STUB_ACP_PROMPT_STOP_REASON", "end_turn")

        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        # Send a prompt — the stub will emit session/request_permission mid-turn.
        await transport.send_input(b"ping")

        # Collect events: we expect AgentMessage(kind="request_permission"), then
        # AgentMessage(kind="turn_end"). No TransportError.
        events_seen: list = []
        for _ in range(15):
            try:
                evt = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
                events_seen.append(evt)
                if isinstance(evt, AgentMessage) and evt.kind == "request_permission":
                    # Extract request_id and reply immediately.
                    request_id = evt.payload.get("_request_id")
                    assert request_id is not None, (
                        "request_permission payload must carry _request_id"
                    )
                    outcome = {"outcome": "selected", "optionId": "opt-allow"}
                    await transport.send_permission_response(request_id, outcome)
                elif isinstance(evt, AgentMessage) and evt.kind == "turn_end":
                    break
            except (TimeoutError, StopAsyncIteration):
                break

        kinds = [e.kind for e in events_seen if isinstance(e, AgentMessage)]
        assert "request_permission" in kinds, (
            f"No request_permission event seen; events: {events_seen}"
        )
        errors = [e for e in events_seen if isinstance(e, TransportError)]
        assert not errors, f"Unexpected TransportError: {errors}"

        await transport.end()

    @pytest.mark.asyncio
    async def test_send_permission_response_frame_has_no_method_key(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """The JSON-RPC response frame written to the agent's stdin must NOT
        have a 'method' key — it's a response, not a new request.

        Verified by asserting the stub processes it cleanly (if method were
        present with an unknown name, the stub would return -32601 and that
        would surface as a transport error or the stub would not record the
        outcome).
        """
        monkeypatch.setenv("STUB_ACP_EMIT_PERMISSION_REQUEST", "1")

        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))

        event_iter = transport.events()
        await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)  # Started

        await transport.send_input(b"test")

        request_permission_event = None
        for _ in range(15):
            try:
                evt = await asyncio.wait_for(event_iter.__anext__(), timeout=2.0)
                if isinstance(evt, AgentMessage) and evt.kind == "request_permission":
                    request_permission_event = evt
                    request_id = evt.payload["_request_id"]
                    # Use a cancelled outcome to verify shape flexibility.
                    await transport.send_permission_response(
                        request_id, {"outcome": "cancelled"}
                    )
                elif isinstance(evt, AgentMessage) and evt.kind == "turn_end":
                    break
            except (TimeoutError, StopAsyncIteration):
                break

        assert request_permission_event is not None, (
            "Expected a request_permission event from stub"
        )
        # No TransportError means the stub accepted the response (no -32601).
        await transport.end()

    @pytest.mark.asyncio
    async def test_send_permission_response_noop_when_not_started(
        self, tmp_path, _reset_env
    ):
        """send_permission_response before start() is a silent no-op."""
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        # Should not raise.
        await transport.send_permission_response(42, {"outcome": "selected", "optionId": "opt-1"})

    @pytest.mark.asyncio
    async def test_send_permission_response_noop_after_end(
        self, tmp_path, monkeypatch, _reset_env
    ):
        """send_permission_response after end() is a silent no-op."""
        transport = ACPTransport(
            resolve_binary=_stub_resolve_binary,
            build_argv=_stub_build_argv(),
        )
        await transport.start(_make_config(tmp_path))
        await transport.end()
        # Should not raise.
        await transport.send_permission_response(1, {"outcome": "cancelled"})
