"""A one-address ``--bind`` also listens on loopback; ``--show-url`` re-prints the sign-in URL.

Review-4 items 3 and 4 (coordinator decisions on the ADR-0019 consequences):

- ``modules/hop.py`` dials ``127.0.0.1:<web_port>`` for ``studyloop drill``'s
  practice_check hop, and every other local consumer assumes loopback. A server
  bound to a tailnet address *alone* was unreachable from them, so a non-loopback
  ``--bind`` now listens on that address AND on ``127.0.0.1``. Host and Origin rules
  (ADR-0014) are per request and unchanged for both listeners.
- The launcher prints the sign-in URL once, before tmux attaches; a closed tab lost
  it. ``studyloop web --show-url`` prints it again from the owner-only session state
  and refuses plainly when no server answers.
"""

from __future__ import annotations

import re
import secrets
import socket
from typing import TYPE_CHECKING, Any

import pytest

from studyloop.web.ws_origin import BOOTSTRAP_TOKEN_ENV

if TYPE_CHECKING:
    from pathlib import Path


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *args: str,
    local: frozenset[str] | None = None,
) -> tuple[dict[str, Any], int, str]:
    """Run ``studyloop web`` up to the point it would serve; capture what it serves on.

    *local* replaces the interface check (see ``test_web_bind.py``); the socket layer
    is left real unless a test stubs ``listen_sockets`` itself.
    """
    import uvicorn
    from click.testing import CliRunner

    from studyloop.cli import cli

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.delenv("STUDYLOOP_WEB_PASSWORD", raising=False)
    monkeypatch.delenv(BOOTSTRAP_TOKEN_ENV, raising=False)
    monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.42",))
    if local is not None:
        monkeypatch.setattr("studyloop.cli._web._is_local_address", lambda a: a in local)
    captured: dict[str, Any] = {}

    def capture(server: Any, sockets: list[socket.socket] | None = None) -> None:
        captured["host"] = server.config.host
        captured["sockets"] = sockets

    monkeypatch.setattr(uvicorn.Server, "run", capture)
    result = CliRunner().invoke(cli, ["web", *args])
    return captured, result.exit_code, result.output


# ---------------------------------------------------------------------------
# Item 3: which addresses a bind listens on
# ---------------------------------------------------------------------------


class TestListenAddresses:
    """The bind list as a pure function of the validated ``--bind`` value."""

    def test_a_non_loopback_address_also_listens_on_loopback(self) -> None:
        from studyloop.cli._web import listen_addresses

        assert listen_addresses("100.101.102.103") == ("100.101.102.103", "127.0.0.1")

    def test_a_non_loopback_ipv6_address_also_listens_on_ipv4_loopback(self) -> None:
        """The hop dials 127.0.0.1, not ::1."""
        from studyloop.cli._web import listen_addresses

        assert listen_addresses("fd7a:115c:a1e0::1") == ("fd7a:115c:a1e0::1", "127.0.0.1")

    @pytest.mark.parametrize("loopback", ["127.0.0.1", "::1", "127.0.0.2"])
    def test_a_loopback_address_is_one_listener(self, loopback: str) -> None:
        from studyloop.cli._web import listen_addresses

        assert listen_addresses(loopback) == (loopback,)

    def test_the_deprecated_wildcard_is_one_listener(self) -> None:
        """0.0.0.0 already includes loopback; a second socket would collide with it."""
        from studyloop.cli._web import listen_addresses

        assert listen_addresses("0.0.0.0") == ("0.0.0.0",)


class TestListenSockets:
    def test_two_addresses_are_two_bound_sockets_on_the_one_port(self) -> None:
        """Real sockets: IPv4 and IPv6 loopback are two distinct addresses this host has.

        192.0.2.x cannot be bound here (RFC 5737 is never assigned), so the two
        loopback families stand in for "bind address + 127.0.0.1" at the socket layer.
        """
        from studyloop.cli._web import listen_sockets

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        sockets = listen_sockets(("::1", "127.0.0.1"), port)
        try:
            assert [s.getsockname()[0] for s in sockets] == ["::1", "127.0.0.1"]
            assert {s.getsockname()[1] for s in sockets} == {port}
            for sock in sockets:
                sock.listen(1)
                family = sock.family
                with socket.socket(family) as client:
                    client.settimeout(2)
                    client.connect(sock.getsockname()[:2])
        finally:
            for sock in sockets:
                sock.close()

    def test_a_port_already_taken_closes_what_was_bound_and_raises(self) -> None:
        """Half a dual bind must not stay open: either both listen or neither does."""
        from studyloop.cli._web import listen_sockets

        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            port = taken.getsockname()[1]
            with pytest.raises(OSError):
                listen_sockets(("::1", "127.0.0.1"), port)
            # ::1 was bound first and must have been released: binding it again works.
            with socket.socket(socket.AF_INET6) as again:
                again.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                again.bind(("::1", port))

    def test_uvicorn_serves_the_app_on_every_pre_bound_socket(self) -> None:
        """The contract the dual bind relies on: ``Server.run(sockets=...)`` serves all of them.

        Two loopback families stand in for "bind address + 127.0.0.1"; the server's
        ``config.host`` names only the first, as it does under ``--bind``.
        """
        import threading
        import urllib.request

        import uvicorn

        from studyloop.cli._web import listen_sockets

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                return
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"both"})

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        sockets = listen_sockets(("::1", "127.0.0.1"), port)
        server = uvicorn.Server(uvicorn.Config(app, host="::1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": sockets}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                threading.Event().wait(0.05)
            assert server.started
            for url in (f"http://127.0.0.1:{port}/", f"http://[::1]:{port}/"):
                with urllib.request.urlopen(url, timeout=5) as response:
                    assert response.read() == b"both", url
        finally:
            server.should_exit = True
            thread.join(timeout=5)


class TestBindServesBoth:
    def test_a_non_loopback_bind_hands_uvicorn_both_listeners(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bound: list[tuple[tuple[str, ...], int]] = []

        def fake_listen_sockets(hosts: tuple[str, ...], port: int) -> list[socket.socket]:
            bound.append((hosts, port))
            return []

        monkeypatch.setattr("studyloop.cli._web.listen_sockets", fake_listen_sockets)
        captured, code, output = _run(
            monkeypatch, tmp_path, "--bind", "100.101.102.103", local=frozenset({"100.101.102.103"})
        )
        assert code == 0, output
        assert bound == [(("100.101.102.103", "127.0.0.1"), 8567)]
        assert captured["sockets"] == [], "run() must take the pre-bound sockets"
        assert captured["host"] == "100.101.102.103"

    def test_a_loopback_bind_keeps_the_single_host_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", "127.0.0.1")
        assert code == 0, output
        assert captured["sockets"] is None
        assert captured["host"] == "127.0.0.1"

    def test_the_printed_addresses_name_both_with_the_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("studyloop.cli._web.listen_sockets", lambda hosts, port: [])
        _, code, output = _run(
            monkeypatch, tmp_path, "--bind", "100.101.102.103", local=frozenset({"100.101.102.103"})
        )
        assert code == 0, output
        tokens = set(re.findall(r"token=([A-Za-z0-9_-]{32,})", output))
        assert len(tokens) == 1, output
        assert re.search(r"http://100\.101\.102\.103:8567/\?token=", output)
        assert re.search(r"http://127\.0\.0\.1:8567/\?token=", output)

    def test_a_bind_that_cannot_be_served_is_refused_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def taken(hosts: tuple[str, ...], port: int) -> list[socket.socket]:
            raise OSError(48, "Address already in use")

        monkeypatch.setattr("studyloop.cli._web.listen_sockets", taken)
        captured, code, output = _run(
            monkeypatch, tmp_path, "--bind", "100.101.102.103", local=frozenset({"100.101.102.103"})
        )
        assert code == 1, output
        assert "sockets" not in captured
        assert "Address already in use" in output
        assert "8567" in output


# ---------------------------------------------------------------------------
# E#5: the loopback hint names --bind
# ---------------------------------------------------------------------------


def test_the_loopback_hint_names_bind_not_lan() -> None:
    from studyloop.web.runtime_feedback import build_web_access_info, format_web_access_lines

    lines = "\n".join(
        format_web_access_lines(
            build_web_access_info(bind_host="127.0.0.1", port=8567, lan_enabled=False)
        )
    )
    assert "--lan" not in lines
    assert "--bind ADDRESS" in lines


# ---------------------------------------------------------------------------
# Item 4: studyloop web --show-url
# ---------------------------------------------------------------------------


def _show_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: dict[str, Any]
) -> tuple[int, str]:
    import uvicorn
    from click.testing import CliRunner

    from studyloop.cli import cli

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setattr("studyloop.session_state.read_session_state", lambda: dict(state))

    def never(*_a: Any, **_k: Any) -> None:
        raise AssertionError("--show-url must not start a server")

    monkeypatch.setattr(uvicorn.Server, "run", never)
    result = CliRunner().invoke(cli, ["web", "--show-url"])
    return result.exit_code, result.output


class TestShowUrl:
    def test_prints_the_launcher_url_with_the_token_when_the_server_answers(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        token = secrets.token_urlsafe(32)
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            code, output = _show_url(
                monkeypatch,
                tmp_path,
                {
                    "web_pid": 4242,
                    "web_port": port,
                    "web_bind_host": "100.101.102.103",
                    "web_sign_in_token": token,
                },
            )
        assert code == 0, output
        assert f"http://100.101.102.103:{port}/session?token={token}" in output
        # One line, so it can be copied or clicked.
        assert any(token in line and "100.101.102.103" in line for line in output.splitlines())

    def test_a_loopback_launch_prints_loopback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        token = secrets.token_urlsafe(32)
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            code, output = _show_url(
                monkeypatch,
                tmp_path,
                {"web_pid": 4242, "web_port": port, "web_sign_in_token": token},
            )
        assert code == 0, output
        assert f"http://127.0.0.1:{port}/session?token={token}" in output

    def test_refuses_when_no_server_answers_on_the_recorded_port(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        code, output = _show_url(
            monkeypatch,
            tmp_path,
            {"web_pid": 4242, "web_port": port, "web_sign_in_token": secrets.token_urlsafe(32)},
        )
        assert code == 1, output
        assert "no studyloop web server" in output.lower()
        assert "token=" not in output, "a dead server's token is not handed out"

    def test_refuses_when_no_session_recorded_a_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, output = _show_url(monkeypatch, tmp_path, {})
        assert code == 1, output
        assert "no studyloop web server" in output.lower()
        assert "studyloop study --web" in output

    def test_refuses_when_the_server_was_started_by_hand(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A hand-run `studyloop web` writes no state; its URL is in the terminal that ran it."""
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            code, output = _show_url(monkeypatch, tmp_path, {"web_port": port})
        assert code == 1, output
        assert "printed where it started" in output

    def test_help_lists_show_url(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from studyloop.cli import cli

        result = CliRunner().invoke(cli, ["web", "--help"])
        assert "--show-url" in result.output
