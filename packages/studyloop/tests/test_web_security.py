"""The web server's request boundary: which Host it answers, which Origin may
open a WebSocket, and the per-process secret on ``/api/*``.

Closes, from the 2026-10-21 full-repo review:

- F-WEB-03@claude: no Host check, and the WS Origin rule accepted Origin == Host,
  so a DNS-rebinding page became same-origin with the learner's StudyLoop.
- F-WEB-20@claude: in default mode loopback was the only gate on the terminal.
- ledger 21 / F-WEB-01@gpt-5.6-terra: ``--lan`` must never bind without a password.

Every test drives the app in-process (``TestClient``); none binds a port.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from studyloop.web.app import create_app

# ---------------------------------------------------------------------------
# F-WEB-03 — Host allowlist (DNS rebinding)
# ---------------------------------------------------------------------------


class TestHostAllowlist:
    def test_foreign_host_header_is_refused(self) -> None:
        """A rebound name reaches 127.0.0.1 with its own name in Host: refuse it."""
        client = TestClient(create_app())
        response = client.get("/api/session/state", headers={"Host": "rebind.example:8567"})
        assert response.status_code in {400, 421}, response.text

    @pytest.mark.parametrize(
        "host",
        ["localhost:8567", "127.0.0.1:8567", "[::1]:8567", "192.168.1.42:8567", "LOCALHOST"],
    )
    def test_own_names_and_ip_literals_are_answered(self, host: str) -> None:
        client = TestClient(create_app())
        assert client.get("/api/session/state", headers={"Host": host}).status_code == 200

    def test_foreign_host_on_the_terminal_socket_is_refused_before_accept(self) -> None:
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(create_app())
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws",
                headers={"Host": "rebind.example:8567", "Origin": "http://localhost"},
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

    def test_hostname_named_in_allowed_origins_is_answered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STUDYLOOP_ALLOWED_ORIGINS", "http://andys-mbp.local:8567")
        client = TestClient(create_app())
        response = client.get("/api/session/state", headers={"Host": "andys-mbp.local:8567"})
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "host",
        ["", "rebind.example", "127.0.0.1.nip.io:8567", "evil.localhost", "localhost:x", "[::1"],
    )
    def test_host_policy_refuses_names_it_does_not_own(self, host: str) -> None:
        from studyloop.web.ws_origin import host_allowed

        assert not host_allowed(host)

    def test_in_process_test_host_is_not_answered_over_a_socket(self) -> None:
        """``testserver`` is honoured only for the in-process client, never by name alone."""
        from studyloop.web.ws_origin import host_allowed, is_in_process_test_scope

        assert not host_allowed("testserver")
        assert not is_in_process_test_scope({"server": ("127.0.0.1", 8567)})
        assert is_in_process_test_scope({"server": ["testserver", 80]})
