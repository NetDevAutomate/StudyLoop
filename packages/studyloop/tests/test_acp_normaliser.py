"""Unit tests for the ACP normaliser (Phase 1.5 spike).

Locks the inbound ``session/update`` → ``AgentMessage`` mapping so
Phase 2 implementation doesn't drift. Also verifies the ACPTransport
skeleton satisfies the AgentSessionTransport Protocol at import time
— if a future refactor changes the Protocol signature, the skeleton
fails to import and we catch it before Phase 2 starts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from studyloop.session.transports.acp import ACPTransport
from studyloop.session.transports.acp_normaliser import (
    DROPPED_UPDATE_KINDS,
    OUTBOUND_METHOD_ALIASES,
    UPDATE_KIND_MAP,
    is_kiro_extension,
    normalise_session_update,
    rewrite_outbound_method,
)

if TYPE_CHECKING:
    from studyloop.session.transport import AgentSessionTransport


class TestOutboundMethodAliases:
    def test_no_aliases_registered_today(self) -> None:
        """Kiro 0.11.131 and Gemini 0.41.2 both accept the spec method
        names; the alias table is empty by design. When a CLI drifts,
        the first alias lands here."""
        assert OUTBOUND_METHOD_ALIASES == {}

    def test_rewrite_is_identity_when_no_alias(self) -> None:
        assert rewrite_outbound_method("session/new", "kiro") == "session/new"
        assert rewrite_outbound_method("session/prompt", "gemini") == "session/prompt"

    def test_rewrite_uses_alias_when_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Smoke-test the extension point for a future CLI that reverts."""
        import studyloop.session.transports.acp_normaliser as mod

        monkeypatch.setitem(
            mod.OUTBOUND_METHOD_ALIASES,
            "hypothetical_agent",
            {"session/new": "newSession"},
        )
        assert rewrite_outbound_method("session/new", "hypothetical_agent") == "newSession"
        # Unrelated agents unaffected.
        assert rewrite_outbound_method("session/new", "kiro") == "session/new"


class TestUpdateKindMap:
    @pytest.mark.parametrize(
        ("acp_kind", "our_kind"),
        [
            ("agent_message_chunk", "agent_chunk"),
            ("agent_thought_chunk", "agent_thought"),
            ("tool_call", "tool_call"),
            ("tool_call_update", "tool_call_update"),
            ("turn_end", "turn_end"),
            ("plan", "plan"),
            ("plan_update", "plan_update"),
            ("available_commands_update", "available_commands"),
        ],
    )
    def test_known_kinds_mapped(self, acp_kind: str, our_kind: str) -> None:
        assert UPDATE_KIND_MAP[acp_kind] == our_kind

    def test_request_permission_not_in_update_kind_map(self) -> None:
        """U6.5: request_permission arrives as a JSON-RPC *request*
        (session/request_permission with an id), NOT as a session/update
        notification. It must NOT be in UPDATE_KIND_MAP — that path is dead."""
        assert "request_permission" not in UPDATE_KIND_MAP

    def test_chrome_drops_documented(self) -> None:
        """DROPPED_UPDATE_KINDS must be a subset of the map's keys
        so we never drop an unmapped kind (which would silently lose
        a frame we don't recognise yet)."""
        assert DROPPED_UPDATE_KINDS.issubset(UPDATE_KIND_MAP.keys())


class TestNormaliseSessionUpdate:
    def test_agent_message_chunk(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "READY"},
            },
        }
        result = normalise_session_update(params)
        assert result is not None
        assert result["kind"] == "agent_chunk"
        assert result["payload"]["content"]["text"] == "READY"
        assert result["payload"]["sessionId"] == "sess-1"
        # Discriminator must be stripped (no double-recording).
        assert "sessionUpdate" not in result["payload"]

    def test_tool_call(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc-42",
                "title": "Read file",
                "kind": "read",
            },
        }
        result = normalise_session_update(params)
        assert result is not None
        assert result["kind"] == "tool_call"
        assert result["payload"]["toolCallId"] == "tc-42"

    def test_available_commands_update_dropped_by_default(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "memory"}],
            },
        }
        assert normalise_session_update(params) is None

    def test_available_commands_update_surfaced_when_drop_chrome_false(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "memory"}],
            },
        }
        result = normalise_session_update(params, drop_chrome=False)
        assert result is not None
        assert result["kind"] == "available_commands"

    def test_unknown_kind_passes_through_verbatim(self) -> None:
        """Forward-compat: a future ACP kind we haven't mapped yet
        surfaces with its raw name rather than being silently lost."""
        params = {
            "sessionId": "sess-1",
            "update": {"sessionUpdate": "future_event_kind", "data": 42},
        }
        result = normalise_session_update(params)
        assert result is not None
        assert result["kind"] == "future_event_kind"
        assert result["payload"]["data"] == 42

    def test_missing_update_field_returns_none(self) -> None:
        assert normalise_session_update({"sessionId": "s"}) is None
        assert normalise_session_update({"sessionId": "s", "update": None}) is None

    def test_missing_discriminator_returns_none(self) -> None:
        params = {"sessionId": "s", "update": {"content": {}}}
        assert normalise_session_update(params) is None


class TestPlanAndPlanUpdateNormalisation:
    """U5 — plan and plan_update wire strings map to the expected kinds."""

    def test_plan_maps_to_plan(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "plan",
                "steps": [
                    {"title": "a", "status": "pending"},
                    {"title": "b", "status": "pending"},
                ],
            },
        }
        result = normalise_session_update(params)
        assert result is not None
        assert result["kind"] == "plan"
        assert result["payload"]["steps"][0]["title"] == "a"
        assert "sessionUpdate" not in result["payload"]

    def test_plan_update_maps_to_plan_update(self) -> None:
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "plan_update",
                "steps": [
                    {"title": "a", "status": "completed"},
                    {"title": "b", "status": "pending"},
                ],
            },
        }
        result = normalise_session_update(params)
        assert result is not None
        assert result["kind"] == "plan_update"
        assert result["payload"]["steps"][0]["status"] == "completed"

    def test_plan_explicit_in_map(self) -> None:
        """Explicit map entry — not just passthrough. Forward-compat guard."""
        assert "plan" in UPDATE_KIND_MAP
        assert UPDATE_KIND_MAP["plan"] == "plan"

    def test_plan_update_explicit_in_map(self) -> None:
        """Explicit map entry — not just passthrough. Forward-compat guard."""
        assert "plan_update" in UPDATE_KIND_MAP
        assert UPDATE_KIND_MAP["plan_update"] == "plan_update"


class TestKiroExtensionDetection:
    @pytest.mark.parametrize(
        "method",
        [
            "_kiro.dev/mcp/server_initialized",
            "_kiro.dev/commands/available",
            "_kiro.dev/metadata",
            "_kiro.dev/subagent/list_update",
        ],
    )
    def test_kiro_extension_matches(self, method: str) -> None:
        assert is_kiro_extension(method) is True

    @pytest.mark.parametrize(
        "method",
        ["session/update", "initialize", "session/new", "session/prompt"],
    )
    def test_spec_methods_are_not_kiro_extensions(self, method: str) -> None:
        assert is_kiro_extension(method) is False


# ---------------------------------------------------------------------------
# Protocol-acceptance smoke test for the ACPTransport skeleton
# ---------------------------------------------------------------------------


class TestACPTransportSkeleton:
    def test_satisfies_agent_session_transport_protocol(self) -> None:
        """Instantiating ACPTransport and binding it to an
        ``AgentSessionTransport``-typed variable must succeed. Mypy /
        pyright also check this statically, but a runtime hasattr
        sweep catches the case where a Protocol method gets added
        and the skeleton wasn't updated."""
        transport = ACPTransport(
            resolve_binary=lambda name: f"/usr/bin/{name}",
            build_argv=lambda cfg: ["/usr/bin/kiro-cli", "acp"],
        )
        # Duck-typed Protocol check — every method must exist.
        required = [
            "start",
            "send_input",
            "resize",
            "events",
            "cancel",
            "end",
            "__aenter__",
            "__aexit__",
        ]
        missing = [m for m in required if not hasattr(transport, m)]
        assert missing == [], f"ACPTransport missing methods: {missing}"

        # The variable binding itself is the Protocol-acceptance proof:
        # if ACPTransport didn't structurally satisfy the Protocol,
        # static type checkers would reject this assignment.
        _: AgentSessionTransport = transport

    # NOTE: the former ``test_methods_raise_not_implemented`` guard was
    # removed when ACPTransport's skeleton landed behaviour. End-to-end
    # coverage now lives in ``test_acp_transport.py`` against the
    # scripted StubACPAgent.


class TestInboundRequestDispatch:
    """U6.5 — session/request_permission arrives as a JSON-RPC request (not a
    session/update notification), so it bypasses the normaliser entirely.

    The dispatch path is tested in test_acp_transport.py via
    TestSendPermissionResponse (live subprocess integration).

    Here we only test what the normaliser correctly does NOT do:
    - request_permission is absent from UPDATE_KIND_MAP (tested above in
      TestUpdateKindMap.test_request_permission_not_in_update_kind_map)
    - Passing a session/update with sessionUpdate='request_permission' falls
      through the normaliser with passthrough behaviour (unknown kind → raw name)
      rather than being in a curated map entry. This documents the NEW dead path
      so future readers understand why the map entry was removed.
    """

    def test_request_permission_as_session_update_passes_through_verbatim(self) -> None:
        """If (hypothetically) a request_permission arrived via session/update,
        the normaliser would pass it through verbatim with kind='request_permission'
        (unknown-kind passthrough). But the real agent will never send it that way.
        This test documents the passthrough behaviour, not correct usage."""
        params = {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "request_permission",
                "toolCallId": "tc-99",
            },
        }
        result = normalise_session_update(params)
        # Passthrough: normaliser doesn't know this kind, so raw name is used.
        assert result is not None
        assert result["kind"] == "request_permission"
        # But this path will never be reached in production — the real wire
        # sends session/request_permission as a JSON-RPC request, not update.

    def test_request_permission_not_in_dropped_kinds(self) -> None:
        """Even if it somehow appeared as a session/update, it wouldn't be
        silently dropped (DROPPED_UPDATE_KINDS only contains chrome)."""
        assert "request_permission" not in DROPPED_UPDATE_KINDS
