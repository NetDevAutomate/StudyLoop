"""``studyloop study --bind`` reaches the web server, and the printed address signs in.

ADR-0019 gave ``studyloop web`` a ``--bind <ip>`` that replaces ``--lan``; the
``study`` launcher kept taking only ``--lan`` and dropped nothing through. ADR-0014
made the sign-in token the credential a browser needs, and the launcher's own
"Dashboard:" line printed the address without it, so a second device landed on the
sign-in page. These tests pin both halves wired (review-4 lane K, E#2 and E#4).

No conftest.py (pluggy conflict with agent-session-tools). All fixtures inline.
"""

from __future__ import annotations

import re
import secrets
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from studyloop.cli._study import study

if TYPE_CHECKING:
    from pathlib import Path

TOKEN = "t0ken-" + "a" * 40
# Reserved for documentation (RFC 5737): never an address of any machine, so a test that
# stubs the interface check cannot accidentally pass on a real one.
ADDRESS = "192.0.2.7"


def _tmux_side_effect(args: list[str], **_kwargs: Any) -> MagicMock:
    if "-V" in args:
        return MagicMock(returncode=0, stdout="tmux 3.4\n", stderr="")
    if "has-session" in args:
        return MagicMock(returncode=1, stdout="", stderr="")
    return MagicMock(returncode=0, stdout="%0\n", stderr="")


# ---------------------------------------------------------------------------
# The CLI option (cli/_study.py)
# ---------------------------------------------------------------------------


class TestStudyBindOption:
    def _invoke(
        self, monkeypatch: pytest.MonkeyPatch, *args: str, local: frozenset[str] = frozenset()
    ) -> tuple[Any, MagicMock]:
        monkeypatch.setattr("studyloop.cli._web._is_local_address", lambda a: a in local)
        monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.42",))
        with patch("studyloop.cli._study._handle_start") as start:
            result = CliRunner().invoke(study, ["Python Decorators", *args])
        return result, start

    def test_bind_reaches_the_launcher_and_implies_web(self, monkeypatch: pytest.MonkeyPatch):
        result, start = self._invoke(monkeypatch, "--bind", ADDRESS, local=frozenset({ADDRESS}))
        assert result.exit_code == 0, result.output
        start.assert_called_once()
        assert start.call_args.args[6] is True, "--bind implies --web"
        assert start.call_args.kwargs["bind"] == ADDRESS

    def test_no_bind_hands_the_launcher_none(self, monkeypatch: pytest.MonkeyPatch):
        result, start = self._invoke(monkeypatch, "--web")
        assert result.exit_code == 0, result.output
        assert "bind" in start.call_args.kwargs, "the launcher must be told explicitly"
        assert start.call_args.kwargs["bind"] is None

    def test_an_address_this_machine_lacks_is_refused_before_anything_starts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        result, start = self._invoke(monkeypatch, "--bind", ADDRESS, local=frozenset({"127.0.0.1"}))
        assert result.exit_code == 2, result.output
        assert "not an address of this machine" in " ".join(result.output.split())
        assert "192.168.1.42" in result.output
        start.assert_not_called()

    @pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
    def test_a_wildcard_is_refused(self, monkeypatch: pytest.MonkeyPatch, wildcard: str):
        result, start = self._invoke(monkeypatch, "--bind", wildcard)
        assert result.exit_code == 2, result.output
        assert "every interface" in result.output
        start.assert_not_called()

    def test_lan_and_bind_together_are_refused(self, monkeypatch: pytest.MonkeyPatch):
        result, start = self._invoke(monkeypatch, "--lan", "--bind", "127.0.0.1")
        assert result.exit_code == 2, result.output
        assert "cannot be combined" in result.output
        start.assert_not_called()

    def test_help_offers_bind_and_marks_lan_deprecated(self):
        result = CliRunner().invoke(study, ["--help"])
        flat = " ".join(result.output.split())
        assert "--bind ADDRESS" in flat
        assert re.search(r"--lan\s+Deprecated", flat), flat


# ---------------------------------------------------------------------------
# The launcher (session/start.py)
# ---------------------------------------------------------------------------


def _start(
    tmp_path: Path,
    *,
    web: bool,
    lan: bool = False,
    bind: str | None = None,
    password: str = "",
    lan_ip: str = "192.168.1.42",
    lan_hosts: tuple[str, ...] | None = None,
) -> MagicMock:
    """Run ``start_session`` with the environment stubbed; return the web-launch spy.

    ``start_web_background`` is the orchestrator's contract: it mints the token and
    hands it back, so the launcher can print an address that signs the browser in.
    """
    from studyloop.session.start import start_session

    launch = MagicMock(return_value=TOKEN)
    with ExitStack() as stack:
        for target, replacement in (
            ("studyloop.tmux.shutil.which", MagicMock(return_value="/usr/bin/tmux")),
            ("studyloop.tmux.subprocess.run", MagicMock(side_effect=_tmux_side_effect)),
            ("studyloop.tmux.os.execvp", MagicMock()),
            ("studyloop.agent_launcher.shutil.which", MagicMock(return_value="/usr/bin/claude")),
            ("studyloop.session_state.read_session_state", MagicMock(return_value={})),
            ("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            ("studyloop.session_state.SESSION_DIR", tmp_path),
            ("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            ("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            ("studyloop.history.start_study_session", MagicMock(return_value="abc12345")),
            ("studyloop.session.cleanup.auto_clean_zombies", MagicMock()),
            ("studyloop.session.orchestrator.start_web_background", launch),
            ("studyloop.session.orchestrator._get_web_port", MagicMock(return_value=8567)),
            # The launcher asks the shared helper (studyloop.web.lan_hosts) for the
            # LAN address, the same one `studyloop web` prints; patched where the
            # launcher looks it up.
            (
                "studyloop.session.start.candidate_lan_hosts",
                MagicMock(return_value=(lan_ip,) if lan_hosts is None else lan_hosts),
            ),
        ):
            stack.enter_context(patch(target, replacement))
        stack.enter_context(
            patch.dict(
                "os.environ",
                {"TMUX": "/tmp/tmux", "STUDYLOOP_CONFIG": str(tmp_path / "config.yaml")},
            )
        )
        start_session(
            "Python Decorators",
            "claude",
            "study",
            "elapsed",
            5,
            web,
            lan=lan,
            password=password,
            bind=bind,
        )
    return launch


class TestLauncherPassesBindThrough:
    def test_bind_reaches_start_web_background(self, tmp_path: Path):
        launch = _start(tmp_path, web=True, bind=ADDRESS)
        launch.assert_called_once()
        assert launch.call_args.kwargs["bind"] == ADDRESS

    def test_a_non_loopback_bind_gets_a_generated_password(self, tmp_path: Path):
        """Same rule as ``--lan`` (ADR-0019): nothing beyond loopback serves without one."""
        launch = _start(tmp_path, web=True, bind=ADDRESS)
        password = launch.call_args.kwargs["password"]
        assert password and len(password) >= 16

    def test_a_loopback_bind_gets_no_password(self, tmp_path: Path):
        launch = _start(tmp_path, web=True, bind="127.0.0.1")
        assert launch.call_args.kwargs["password"] == ""

    def test_an_explicit_password_is_kept(self, tmp_path: Path):
        chosen = secrets.token_urlsafe(8)
        launch = _start(tmp_path, web=True, bind=ADDRESS, password=chosen)
        assert launch.call_args.kwargs["password"] == chosen


class TestPrintedAddressCarriesTheToken:
    """E#4: the launcher's own address line must sign a browser in (ADR-0014)."""

    def test_bind_prints_the_bound_address_with_the_token(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        _start(tmp_path, web=True, bind=ADDRESS)
        out = capsys.readouterr().out
        line = next((ln for ln in out.splitlines() if "Dashboard:" in ln), "")
        assert f"http://{ADDRESS}:8567/session?token={TOKEN}" in line, out

    def test_lan_prints_the_lan_address_with_the_token(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        _start(tmp_path, web=True, lan=True, lan_ip="192.168.1.42")
        out = capsys.readouterr().out
        line = next((ln for ln in out.splitlines() if "Dashboard:" in ln), "")
        assert f"http://192.168.1.42:8567/session?token={TOKEN}" in line, out

    def test_lan_skips_a_loopback_candidate_for_the_first_reachable_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A hostname resolving to 127.0.1.1 (Debian's default) is no use to another device.

        The launcher used to print whatever ``gethostbyname`` said; it now hands
        every candidate to ``build_web_access_info``, which drops the loopback.
        """
        _start(tmp_path, web=True, lan=True, lan_hosts=("127.0.1.1", "192.168.1.42"))
        out = capsys.readouterr().out
        line = next((ln for ln in out.splitlines() if "Dashboard:" in ln), "")
        assert f"http://192.168.1.42:8567/session?token={TOKEN}" in line, out

    def test_the_address_is_printed_on_one_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A URL folded across two lines cannot be copied or clicked."""
        _start(tmp_path, web=True, bind=ADDRESS)
        out = capsys.readouterr().out
        assert TOKEN in out
        assert any(TOKEN in ln and ADDRESS in ln for ln in out.splitlines()), out

    def test_the_password_is_not_persisted_in_the_session_state(self, tmp_path: Path):
        """The browser-facing state endpoint echoes keys not named ``*_token``/``*_secret``."""
        import json

        _start(tmp_path, web=True, lan=True)
        state = json.loads((tmp_path / "state.json").read_text())
        assert "lan_password" not in state
        assert not any(v == TOKEN for k, v in state.items() if not k.endswith("_token"))


class TestOrchestratorReturnsTheToken:
    def _launch(self, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> tuple[Any, dict]:
        from studyloop.session import orchestrator

        seen: dict[str, Any] = {}
        written: dict[str, Any] = {}

        class _Proc:
            pid = 4242

        def fake_popen(cmd: list[str], **popen_kwargs: Any) -> _Proc:
            seen["env"] = popen_kwargs["env"]
            return _Proc()

        monkeypatch.setattr(orchestrator, "_kill_port_occupant", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "_get_web_port", lambda: 8567)
        monkeypatch.setattr(orchestrator.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(orchestrator, "_open_browser", lambda url, **k: seen.update(url=url))
        monkeypatch.setattr("studyloop.session_state.write_session_state", written.update)
        token = orchestrator.start_web_background("study-test", **kwargs)
        return token, {"seen": seen, "written": written}

    def test_the_token_handed_back_is_the_one_the_child_and_browser_got(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from studyloop.web.ws_origin import BOOTSTRAP_TOKEN_ENV

        token, ctx = self._launch(monkeypatch)
        assert token and len(token) >= 32
        assert ctx["seen"]["env"][BOOTSTRAP_TOKEN_ENV] == token
        assert ctx["seen"]["url"].endswith(f"/session?token={token}")

    def test_the_token_and_bound_host_are_kept_in_the_owner_only_state(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """So ``studyloop web --show-url`` can re-print the address after a tab is closed.

        The key ends in ``_token``: the browser-facing state endpoint strips those.
        """
        token, ctx = self._launch(monkeypatch, bind=ADDRESS)
        assert ctx["written"]["web_sign_in_token"] == token
        assert ctx["written"]["web_bind_host"] == ADDRESS

    def test_no_bind_records_loopback_as_the_host(self, monkeypatch: pytest.MonkeyPatch):
        _, ctx = self._launch(monkeypatch)
        assert ctx["written"]["web_bind_host"] == "127.0.0.1"

    def test_a_failed_launch_hands_back_none(self, monkeypatch: pytest.MonkeyPatch):
        from studyloop.session import orchestrator

        def boom(*_a: Any, **_k: Any) -> None:
            raise OSError("no studyloop on PATH")

        monkeypatch.setattr(orchestrator, "_kill_port_occupant", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "_get_web_port", lambda: 8567)
        monkeypatch.setattr(orchestrator.subprocess, "Popen", boom)
        assert orchestrator.start_web_background("study-test") is None
