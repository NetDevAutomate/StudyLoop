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

from typing import TYPE_CHECKING, Any

import pytest
from _helpers import run_async
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import StubTransport  # pyright: ignore[reportAttributeAccessIssue]
from studyloop.session import active
from studyloop.session.transport import SessionConfig, Started
from studyloop.web.app import create_app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _no_live_session():
    run_async(active.release())
    yield
    run_async(active.release())


def _start_stub_session(tmp_path: Path) -> None:
    config = SessionConfig(
        study_session_id="study-1",
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )
    stub = StubTransport(events=[Started(agent="claude")])
    run_async(active.acquire(config, lambda: stub))


def _run_studyloop_web(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *args: str
) -> tuple[dict[str, Any], str]:
    """Run ``studyloop web`` up to the point it would serve; return what it would serve.

    ``uvicorn.Server.run`` is replaced so nothing binds a port; the captured
    app is the exact object the real command hands to uvicorn.
    """
    import uvicorn
    from click.testing import CliRunner

    from studyloop.cli import cli

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.delenv("STUDYLOOP_WEB_PASSWORD", raising=False)
    monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.42",))
    captured: dict[str, Any] = {}

    def capture(server: Any, *_args: Any, **_kwargs: Any) -> None:
        captured["app"] = server.config.app
        captured["host"] = server.config.host

    monkeypatch.setattr(uvicorn.Server, "run", capture)
    result = CliRunner().invoke(cli, ["web", *args])
    assert result.exit_code == 0, result.output
    return captured, result.output


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


# ---------------------------------------------------------------------------
# F-WEB-03 — WebSocket Origin no longer trusts the request's own Host
# ---------------------------------------------------------------------------


class TestOriginPolicy:
    def test_ws_origin_equal_to_foreign_host_is_refused(self) -> None:
        """Under rebinding Origin and Host are BOTH the attacker's name: equal, and foreign."""
        from studyloop.web.ws_origin import origin_allowed

        assert not origin_allowed("http://rebind.example:8567", host="rebind.example:8567")

    @pytest.mark.parametrize(
        ("origin", "host", "allowed"),
        [
            ("http://192.168.1.20:8567", "192.168.1.20:8567", True),  # LAN, same-origin
            ("http://[::1]:5173", "127.0.0.1:8567", True),  # loopback dev origin
            ("http://1.2.3.4", "127.0.0.1:8567", False),  # cross-site page by IP
            ("http://testserver", "testserver", False),  # name alone grants nothing
        ],
    )
    def test_origin_matrix(self, origin: str, host: str, allowed: bool) -> None:
        from studyloop.web.ws_origin import origin_allowed

        assert origin_allowed(origin, host=host) is allowed


# ---------------------------------------------------------------------------
# F-WEB-20 — per-process server secret on /api/* and both WebSockets
# ---------------------------------------------------------------------------


class TestServerSecret:
    def test_ws_without_server_secret_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A client that never loaded the page gets no terminal, even with a loopback Origin."""
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        _start_stub_session(tmp_path)
        client = TestClient(captured["app"])

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws", headers={"Origin": "http://localhost"}
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

    def test_browser_flow_with_the_cookie_from_index_reaches_api_and_terminal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The normal flow: load ``/``, keep its cookie, then the API and the terminal work."""
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        _start_stub_session(tmp_path)
        client = TestClient(captured["app"])

        index = client.get("/")
        assert index.status_code == 200
        set_cookie = index.headers["set-cookie"]
        assert set_cookie.startswith("studyloop_auth=")
        assert "httponly" in set_cookie.lower()
        assert "samesite=strict" in set_cookie.lower()

        assert client.get("/api/session/state").status_code == 200
        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1", headers={"Origin": "http://localhost"}
        ) as ws:
            assert ws.receive_json() == {"type": "started", "agent": "claude"}

    @pytest.mark.parametrize(
        "cookie",
        [None, "studyloop_auth=wrong", "studyloop_auth=caf\u00e9".encode(), "other=1"],
    )
    def test_api_request_without_the_right_cookie_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cookie: str | bytes | None
    ) -> None:
        """Covers the cross-site form post too: SameSite=Strict means it arrives with no cookie.

        The non-ASCII value goes on the wire as raw UTF-8 bytes: a constant-time
        compare on ``str`` would raise on it and turn a refusal into a 500.
        """
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        client = TestClient(captured["app"])
        headers: dict[str, Any] = {"Cookie": cookie} if cookie else {}

        response = client.post("/api/session/end", headers=headers)

        assert response.status_code == 403
        assert response.json()["code"] == "server_secret_required"

    def test_content_generation_socket_also_requires_the_secret(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        client = TestClient(captured["app"])
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/content/generate/ws?job_id=gen-x", headers={"Origin": "http://localhost"}
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

    def test_practice_check_hop_keeps_its_own_capability_gate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``studyloop drill`` has no browser cookie; its route checks its own token."""
        from studyloop.modules.hop import ROUTE

        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        client = TestClient(captured["app"])
        response = client.post(ROUTE, json={})
        assert response.json().get("code") != "server_secret_required"

    def test_secret_is_never_printed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        captured, output = _run_studyloop_web(monkeypatch, tmp_path)
        client = TestClient(captured["app"])
        client.get("/")
        secret = client.cookies["studyloop_auth"]
        assert len(secret) >= 32
        assert secret not in output

    def test_each_studyloop_web_process_mints_its_own_secret(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        secrets_seen = set()
        for _ in range(2):
            captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
            client = TestClient(captured["app"])
            client.get("/")
            secrets_seen.add(client.cookies["studyloop_auth"])
        assert len(secrets_seen) == 2

    def test_lan_401_does_not_hand_out_the_cookie(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The cookie is set on a successful ``/`` only, never beside a Basic-auth refusal."""
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path, "--lan")
        client = TestClient(captured["app"])
        response = client.get("/", headers={"Host": "192.168.1.42:8567"})
        assert response.status_code == 401
        assert "set-cookie" not in response.headers

    def test_in_process_create_app_leaves_the_cookie_gate_off(self) -> None:
        """``create_app()`` without a secret (tests, embedding) keeps today's behaviour."""
        response = TestClient(create_app()).get("/api/session/state")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# ledger 21 / F-WEB-01@gpt-5.6-terra — --lan never serves without a password
# ---------------------------------------------------------------------------


class TestLanFailsClosed:
    """The plan's RED 3 expected ``--lan`` with no password to bind open today.

    It does not: with no ``--password`` and no ``lan_password``, ``studyloop web``
    generates one and prints it (``cli/_web.py``), and ``studyloop study --lan``
    does the same in the parent (``session/start.py``). These tests pin that
    fail-closed invariant on the real command path, so removing the generation
    cannot silently put the terminal on 0.0.0.0 behind nothing.
    """

    @pytest.mark.parametrize("config_text", [None, 'lan_password: ""\n'])
    def test_lan_mode_never_serves_without_a_password(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_text: str | None
    ) -> None:
        import base64
        import re

        if config_text is not None:
            (tmp_path / "config.yaml").write_text(config_text)
        captured, output = _run_studyloop_web(monkeypatch, tmp_path, "--lan")
        assert captured["host"] == "0.0.0.0"
        lan = {"Host": "192.168.1.42:8567"}
        client = TestClient(captured["app"])

        assert client.get("/", headers=lan).status_code == 401
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws", headers={**lan, "Origin": "http://192.168.1.42:8567"}
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

        match = re.search(r"Password: (\S+)", output)
        assert match, f"the generated password must be shown, or nobody can sign in:\n{output}"
        token = base64.b64encode(f"study:{match.group(1)}".encode()).decode()
        signed_in = client.get("/", headers={**lan, "Authorization": f"Basic {token}"})
        assert signed_in.status_code == 200

    def test_setup_guide_lan_section_carries_the_cleartext_caveats(self) -> None:
        """Ledger 21: the documented acceptance warning, in the section a ``--lan`` user reads."""
        from pathlib import Path

        guide = Path(__file__).resolve().parents[3] / "docs" / "setup-guide.md"
        text = guide.read_text(encoding="utf-8")
        section = text.split("### Remote Study (iPad on the Bus)", 1)[1].split("\n### ", 1)[0]
        for caveat in (
            "Basic authentication does **not** encrypt the password, requests, responses or "
            "terminal traffic.",
            "LAN peers or intermediaries able to observe traffic may steal credentials and study "
            "content; active intermediaries may tamper with traffic.",
            "Never reuse a password, expose this mode directly to the Internet, or treat "
            "public/shared Wi-Fi as trusted.",
            "Prefer loopback access through an authenticated encrypted tunnel, or a correctly "
            "configured HTTPS/WSS reverse proxy with the application bound to loopback.",
            "`0.0.0.0` exposes every IPv4 interface unless a firewall restricts access.",
        ):
            assert f"- {caveat}" in section, caveat
