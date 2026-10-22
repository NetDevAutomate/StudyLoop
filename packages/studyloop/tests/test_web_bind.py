"""``studyloop web --bind <address>`` replaces ``--lan``'s ``0.0.0.0`` (D7, council pass 3).

``--lan`` bound every interface of every network the machine ever joined and sent
Basic auth over cleartext. The ruling keeps a second-device path but removes the
accidental exposure: ``--bind`` serves on ONE address the machine actually has (a
Tailscale/VPN interface address is the recommended one, where the traffic is
encrypted), validated before anything is served. ``--lan`` stays for one release
as a deprecated alias for ``--bind 0.0.0.0`` and says so. The password is
unchanged and stays fail-closed (``test_web_security.py::TestLanFailsClosed``):
Basic auth is a password gate on an already-private link, not a second factor.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING, Any

import pytest

from studyloop.web.ws_origin import BOOTSTRAP_TOKEN_ENV

if TYPE_CHECKING:
    from pathlib import Path


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *args: str,
    local: set[str] | None = None,
) -> tuple[dict[str, Any], int, str]:
    """Run ``studyloop web`` up to the point it would serve.

    *local* replaces the machine's interface check with a fixed set, so a test
    does not depend on which addresses this host has. Omitted, the real check runs.
    See ``test_web_bind_loopback.py`` for what a non-loopback bind listens on.
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
        # A stubbed interface check means the address is not really here, so the
        # socket layer (which a non-loopback bind now reaches, item 3) is stubbed too.
        monkeypatch.setattr("studyloop.cli._web.listen_sockets", lambda hosts, port: [])
    captured: dict[str, Any] = {}

    def capture(server: Any, *_args: Any, **_kwargs: Any) -> None:
        captured["host"] = server.config.host
        captured["app"] = server.config.app

    monkeypatch.setattr(uvicorn.Server, "run", capture)
    result = CliRunner().invoke(cli, ["web", *args])
    return captured, result.exit_code, result.output


class TestBindValidation:
    def test_an_address_this_machine_lacks_is_refused_with_the_candidates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(
            monkeypatch, tmp_path, "--bind", "10.0.0.5", local={"127.0.0.1", "192.168.1.42"}
        )
        assert code == 2, output
        assert captured == {}, "nothing may be served on a refused address"
        assert "not an address of this machine" in " ".join(output.split())
        assert "10.0.0.5" in output
        assert "192.168.1.42" in output and "127.0.0.1" in output

    def test_the_real_interface_check_refuses_a_documentation_address(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """192.0.2.0/24 (RFC 5737) is never assigned, so the kernel refuses the bind."""
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", "192.0.2.55")
        assert code == 2, output
        assert captured == {}
        assert "not an address of this machine" in " ".join(output.split())

    @pytest.mark.parametrize("value", ["my-mac.local", "300.1.1.1", ""])
    def test_a_value_that_is_not_an_ip_address_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", value)
        assert code == 2, output
        assert captured == {}
        assert "IP address" in output

    @pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
    def test_a_wildcard_is_refused_because_it_is_every_interface(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wildcard: str
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", wildcard)
        assert code == 2, output
        assert captured == {}
        assert "every interface" in output

    def test_lan_and_bind_together_are_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--lan", "--bind", "127.0.0.1")
        assert code == 2, output
        assert captured == {}
        assert "cannot be combined" in output


class TestBindServes:
    def test_a_present_address_is_where_uvicorn_binds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(
            monkeypatch, tmp_path, "--bind", "100.101.102.103", local={"100.101.102.103"}
        )
        assert code == 0, output
        assert captured["host"] == "100.101.102.103"
        # The printed sign-in URL is on that address, token included.
        assert re.search(r"http://100\.101\.102\.103:8567/\?token=[A-Za-z0-9_-]{32,}", output)

    def test_a_non_loopback_bind_never_serves_without_a_password(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import base64

        from fastapi.testclient import TestClient

        captured, code, output = _run(
            monkeypatch, tmp_path, "--bind", "100.101.102.103", local={"100.101.102.103"}
        )
        assert code == 0, output
        client = TestClient(captured["app"])
        here = {"Host": "100.101.102.103:8567"}
        assert client.get("/", headers=here).status_code == 401
        match = re.search(r"Password: (\S+)", output)
        assert match, output
        basic = base64.b64encode(f"study:{match.group(1)}".encode()).decode()
        assert client.get("/", headers={**here, "Authorization": f"Basic {basic}"}).status_code == (
            200
        )

    def test_a_loopback_bind_is_the_default_behaviour_with_no_password(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", "127.0.0.1")
        assert code == 0, output
        assert captured["host"] == "127.0.0.1"
        assert "Password:" not in output

    def test_the_ipv6_loopback_binds_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--bind", "::1", local={"::1"})
        assert code == 0, output
        assert captured["host"] == "::1"
        assert "http://[::1]:8567/?token=" in output


class TestLanIsADeprecatedAlias:
    def test_lan_says_it_is_deprecated_and_names_bind(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, code, output = _run(monkeypatch, tmp_path, "--lan")
        assert code == 0, output
        assert captured["host"] == "0.0.0.0"
        assert re.search(r"--lan is deprecated.*--bind", output, re.DOTALL), output

    def test_lan_prints_the_five_cleartext_caveats(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _, _, output = _run(monkeypatch, tmp_path, "--lan")
        flat = " ".join(output.split())
        for fragment in (
            "Basic authentication does not encrypt",
            "may steal credentials and study content",
            "Never reuse a password",
            "encrypted tunnel",
            "0.0.0.0 exposes every IPv4 interface",
        ):
            assert fragment in flat, fragment

    def test_lan_without_a_password_still_generates_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _, code, output = _run(monkeypatch, tmp_path, "--lan")
        assert code == 0, output
        match = re.search(r"Password: (\S+)", output)
        assert match and len(match.group(1)) >= 16, output

    def test_the_help_text_offers_bind_and_marks_lan_deprecated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _, code, output = _run(monkeypatch, tmp_path, "--help")
        assert code == 0
        flat = " ".join(output.split())
        assert "--bind" in flat
        assert re.search(r"--lan\s+Deprecated", flat), flat
        assert "second factor" not in flat.lower()


class TestLauncherBind:
    def _launch(self, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> dict[str, Any]:
        from studyloop.session import orchestrator

        seen: dict[str, Any] = {}

        class _Proc:
            pid = 4242

        def fake_popen(cmd: list[str], **popen_kwargs: Any) -> _Proc:
            seen["cmd"] = [str(part) for part in cmd]
            return _Proc()

        def fake_open_browser(url: str, **open_kwargs: Any) -> None:
            seen["url"] = url
            seen["ready_url"] = open_kwargs.get("ready_url")

        monkeypatch.setattr(orchestrator, "_kill_port_occupant", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "_get_web_port", lambda: 8567)
        monkeypatch.setattr(orchestrator.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(orchestrator, "_open_browser", fake_open_browser)
        monkeypatch.setattr("studyloop.session_state.write_session_state", lambda *_a: None)
        orchestrator.start_web_background("study-test", **kwargs)
        return seen

    def test_bind_is_passed_through_to_the_child_and_the_browser_opens_there(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._launch(monkeypatch, bind="100.101.102.103", password=secrets.token_urlsafe(8))
        cmd = seen["cmd"]
        assert cmd[cmd.index("--bind") + 1] == "100.101.102.103"
        assert "--lan" not in cmd
        assert seen["url"].startswith("http://100.101.102.103:8567/session?token=")
        assert seen["ready_url"] == "http://100.101.102.103:8567/"

    def test_no_bind_keeps_loopback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._launch(monkeypatch)
        assert "--bind" not in seen["cmd"]
        assert seen["url"].startswith("http://127.0.0.1:8567/session?token=")

    def test_an_ipv6_bind_opens_a_bracketed_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._launch(monkeypatch, bind="::1")
        assert seen["url"].startswith("http://[::1]:8567/session?token=")

    def test_the_deprecated_lan_flag_still_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._launch(monkeypatch, lan=True, password=secrets.token_urlsafe(8))
        assert "--lan" in seen["cmd"]
        assert "--bind" not in seen["cmd"]
        assert seen["url"].startswith("http://127.0.0.1:8567/session?token=")
