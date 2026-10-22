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
    monkeypatch.delenv("STUDYLOOP_WEB_TOKEN", raising=False)
    monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.42",))
    captured: dict[str, Any] = {}

    def capture(server: Any, *_args: Any, **_kwargs: Any) -> None:
        captured["app"] = server.config.app
        captured["host"] = server.config.host

    monkeypatch.setattr(uvicorn.Server, "run", capture)
    result = CliRunner().invoke(cli, ["web", *args])
    assert result.exit_code == 0, result.output
    return captured, result.output


def _printed_token(output: str) -> str:
    """The sign-in token ``studyloop web`` printed inside its URL (D2)."""
    import re

    match = re.search(r"\?token=([A-Za-z0-9_-]{32,})", output)
    assert match, f"studyloop web printed no sign-in URL:\n{output}"
    return match.group(1)


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
            # D9.2 (council pass 3): SameSite does not partition by port, so a page
            # on ANOTHER loopback port would drive the socket with the cookie. A
            # loopback Origin is admitted on this server's own port only. (This row
            # was `True` -- "loopback dev origin" -- before the ruling.)
            ("http://[::1]:5173", "127.0.0.1:8567", False),
            ("http://127.0.0.1:9999", "127.0.0.1:8567", False),
            ("http://localhost:9999", "localhost:8567", False),
            ("http://127.0.0.1:8567", "127.0.0.1:8567", True),  # same port
            ("http://localhost:8567", "127.0.0.1:8567", True),  # same server, other name
            ("http://[::1]:8567", "localhost:8567", True),
            ("http://localhost", "127.0.0.1:80", True),  # default port is port 80
            ("http://localhost", "127.0.0.1:8567", False),
            ("https://localhost", "localhost:443", True),
            ("http://127.0.0.1:8567", "", False),  # no Host: nothing to match
            ("http://1.2.3.4", "127.0.0.1:8567", False),  # cross-site page by IP
            ("http://testserver", "testserver", False),  # name alone grants nothing
        ],
    )
    def test_origin_matrix(self, origin: str, host: str, allowed: bool) -> None:
        from studyloop.web.ws_origin import origin_allowed

        assert origin_allowed(origin, host=host) is allowed

    def test_an_allowlisted_exact_loopback_origin_on_another_port_is_admitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The explicit dev escape hatch (``STUDYLOOP_ALLOWED_ORIGINS``), exact match only."""
        from studyloop.web.ws_origin import origin_allowed

        monkeypatch.setenv("STUDYLOOP_ALLOWED_ORIGINS", "http://127.0.0.1:9999")
        assert origin_allowed("http://127.0.0.1:9999", host="127.0.0.1:8567")
        assert not origin_allowed("http://127.0.0.1:9998", host="127.0.0.1:8567")
        assert not origin_allowed("http://localhost:9999", host="127.0.0.1:8567")

    def test_in_process_client_has_no_port_to_differ_from(self) -> None:
        """``testserver`` never crossed a socket: there is no listening port, so the
        port rule has nothing to compare. Only with the in-process flag, as for Host."""
        from studyloop.web.ws_origin import origin_allowed

        assert origin_allowed("http://127.0.0.1:8788", host="testserver", in_process_test=True)
        assert not origin_allowed("http://127.0.0.1:8788", host="testserver")
        assert not origin_allowed("http://1.2.3.4", host="testserver", in_process_test=True)

    def test_terminal_socket_from_another_loopback_port_is_refused_before_accept(
        self, tmp_path: Path
    ) -> None:
        """End to end in-process, with a real loopback Host: 1008, never accepted."""
        _start_stub_session(tmp_path)
        client = TestClient(create_app())
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws?study_session_id=study-1",
                headers={"Host": "127.0.0.1:8567", "Origin": "http://127.0.0.1:9999"},
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

    def test_terminal_socket_from_the_same_port_is_accepted(self, tmp_path: Path) -> None:
        _start_stub_session(tmp_path)
        client = TestClient(create_app())
        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Host": "127.0.0.1:8567", "Origin": "http://localhost:8567"},
        ) as ws:
            assert ws.receive_json() == {"type": "started", "agent": "claude"}


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

    def test_browser_flow_with_the_cookie_from_the_sign_in_reaches_api_and_terminal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The normal flow: open the printed sign-in URL, keep its cookie, then the API
        and the terminal work. (Before D2 a bare ``/`` handed the cookie out.)"""
        captured, output = _run_studyloop_web(monkeypatch, tmp_path)
        _start_stub_session(tmp_path)
        client = TestClient(captured["app"])

        assert "set-cookie" not in client.get("/").headers
        sign_in = client.get(f"/?token={_printed_token(output)}", follow_redirects=False)
        assert sign_in.status_code == 303
        set_cookie = sign_in.headers["set-cookie"]
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

    def test_secret_is_printed_only_inside_the_sign_in_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """D2 changed this contract: the secret was never printed; now it is printed
        once, as the token in the sign-in URL (Jupyter's model), and nowhere else."""
        captured, output = _run_studyloop_web(monkeypatch, tmp_path)
        token = _printed_token(output)
        client = TestClient(captured["app"])
        client.get(f"/?token={token}")
        secret = client.cookies["studyloop_auth"]
        assert len(secret) >= 32
        assert secret == token
        assert output.count(secret) == 1
        assert f"http://127.0.0.1:8567/?token={secret}" in output

    def test_each_studyloop_web_process_mints_its_own_secret(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        secrets_seen = set()
        for _ in range(2):
            captured, output = _run_studyloop_web(monkeypatch, tmp_path)
            client = TestClient(captured["app"])
            client.get(f"/?token={_printed_token(output)}")
            secrets_seen.add(client.cookies["studyloop_auth"])
        assert len(secrets_seen) == 2

    def test_lan_401_does_not_hand_out_the_cookie(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The cookie never comes beside a Basic-auth refusal, even for the right token."""
        captured, output = _run_studyloop_web(monkeypatch, tmp_path, "--lan")
        client = TestClient(captured["app"])
        lan = {"Host": "192.168.1.42:8567"}
        response = client.get("/", headers=lan)
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        signed = client.get(f"/?token={_printed_token(output)}", headers=lan)
        assert signed.status_code == 401
        assert "set-cookie" not in signed.headers

    def test_in_process_create_app_leaves_the_cookie_gate_off(self) -> None:
        """``create_app()`` without a secret (tests, embedding) keeps today's behaviour."""
        response = TestClient(create_app()).get("/api/session/state")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# D9.1 (council pass 3) — course artefacts outside /api sit behind the cookie too
# ---------------------------------------------------------------------------

_ARTEFACT_SECRET = "a" * 43


@pytest.fixture()
def artefact_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    """``create_app`` with a server secret over a content tree holding one artefact."""
    from unittest.mock import patch

    from studyloop.settings import ContentConfig, Settings

    audio = tmp_path / "content" / "my-course" / "audio"
    audio.mkdir(parents=True)
    (audio / "episode-01.mp3").write_bytes(b"fake-audio")
    (tmp_path / "outside.txt").write_text("not course content")
    settings = Settings(content=ContentConfig(base_path=tmp_path / "content"))
    with patch("studyloop.web.routes.artefacts.load_settings", return_value=settings):
        yield create_app(server_secret=_ARTEFACT_SECRET)


class TestArtefactsRequireTheCookie:
    """Under D2 ``/artefacts/...`` was the one unauthenticated read of learner content
    left: it is served outside ``/api`` and so sat outside the cookie gate."""

    def test_uncookied_artefact_fetch_is_refused(self, artefact_app) -> None:  # type: ignore[no-untyped-def]
        response = TestClient(artefact_app).get("/artefacts/my-course/audio/episode-01.mp3")
        assert response.status_code == 403
        assert response.json()["code"] == "server_secret_required"

    def test_the_dashboard_cookie_fetches_it(self, artefact_app) -> None:  # type: ignore[no-untyped-def]
        """The positive browser path: the page already holds the cookie, ``Path=/``."""
        client = TestClient(artefact_app)
        client.get(f"/?token={_ARTEFACT_SECRET}", follow_redirects=False)
        response = client.get("/artefacts/my-course/audio/episode-01.mp3")
        assert response.status_code == 200
        assert response.content == b"fake-audio"

    @pytest.mark.parametrize(
        "path",
        ["/artefacts/../outside.txt", "/artefacts/my-course/../../outside.txt"],
    )
    def test_traversal_is_still_404_with_the_cookie(self, artefact_app, path: str) -> None:  # type: ignore[no-untyped-def]
        client = TestClient(artefact_app)
        client.cookies.set("studyloop_auth", _ARTEFACT_SECRET)
        assert client.get(path).status_code == 404

    def test_encoded_traversal_is_still_404_with_the_cookie(self, artefact_app) -> None:  # type: ignore[no-untyped-def]
        client = TestClient(artefact_app)
        client.cookies.set("studyloop_auth", _ARTEFACT_SECRET)
        response = client.get("/artefacts/my-course/audio/..%2F..%2F..%2Foutside.txt")
        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("path", "gated"),
        [
            ("/artefacts/c/t/f.mp3", True),
            ("/artefacts", True),
            ("/artefacts/", True),
            ("/artefactsx/f", False),
            ("/static/app.js", False),
        ],
    )
    def test_gate_covers_exactly_the_artefact_route(self, path: str, gated: bool) -> None:
        from studyloop.web.ws_origin import requires_server_secret

        assert requires_server_secret(path) is gated


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
