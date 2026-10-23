"""One answer to "which address does another device reach this machine at".

``studyloop web`` (``cli/_web.py``) and the session launcher (``session/start.py``)
each print a dashboard address for a second device. The launcher used to ask
``socket.gethostbyname(socket.gethostname())`` on its own, while the CLI had
``_candidate_lan_hosts`` with a routing probe first -- two implementations of
"the LAN address" that would drift (review 5, steer row I). Both now import
``studyloop.web.lan_hosts.candidate_lan_hosts``; the launcher stays Click-free,
which is its documented contract.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src" / "studyloop"


def _imports_of(path: Path) -> set[str]:
    """Top-level names of every module a file imports, including function-local imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class TestTheHelperIsClickFree:
    @pytest.mark.parametrize(
        "relative",
        ["web/lan_hosts.py", "session/start.py"],
        ids=["helper", "launcher"],
    )
    def test_neither_module_imports_click(self, relative: str) -> None:
        """``session/start.py`` is framework-agnostic by contract (its docstring);

        the helper it imports must not smuggle Click in.
        """
        assert "click" not in _imports_of(_SRC / relative), relative

    def test_the_launcher_no_longer_resolves_the_address_itself(self) -> None:
        """The launcher asks the shared helper, not ``gethostbyname`` directly."""
        source = (_SRC / "session" / "start.py").read_text(encoding="utf-8")
        assert "gethostbyname" not in source, (
            "session/start.py resolves the LAN address on its own; it must call "
            "studyloop.web.lan_hosts.candidate_lan_hosts so the CLI and the launcher agree"
        )

    def test_the_cli_uses_the_same_function(self) -> None:
        """``cli/_web.py`` keeps its private name as a re-export of the one helper."""
        from studyloop.cli import _web
        from studyloop.web import lan_hosts

        assert _web._candidate_lan_hosts is lan_hosts.candidate_lan_hosts


class TestCandidateLanHosts:
    def test_the_routing_probe_comes_first_then_the_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyloop.web import lan_hosts

        class FakeSocket:
            def __init__(self, *args: object) -> None:
                pass

            def __enter__(self) -> FakeSocket:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def connect(self, address: tuple[str, int]) -> None:
                assert address == ("8.8.8.8", 80)

            def getsockname(self) -> tuple[str, int]:
                return ("192.168.1.42", 54321)

        monkeypatch.setattr(lan_hosts.socket, "socket", FakeSocket)
        monkeypatch.setattr(lan_hosts.socket, "gethostname", lambda: "studybox")
        monkeypatch.setattr(lan_hosts.socket, "gethostbyname", lambda name: "10.0.0.7")

        assert lan_hosts.candidate_lan_hosts() == ("192.168.1.42", "10.0.0.7")

    def test_a_failed_probe_is_skipped_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No default route and a hostname that does not resolve: an empty answer, no raise."""
        from studyloop.web import lan_hosts

        def no_route(*args: object) -> socket.socket:
            raise OSError("Network is unreachable")

        monkeypatch.setattr(lan_hosts.socket, "socket", no_route)
        monkeypatch.setattr(lan_hosts.socket, "gethostname", lambda: "studybox")

        def unresolvable(name: str) -> str:
            raise socket.gaierror("nodename nor servname provided")

        monkeypatch.setattr(lan_hosts.socket, "gethostbyname", unresolvable)

        assert lan_hosts.candidate_lan_hosts() == ()
